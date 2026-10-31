//! Shared `cfg(test)` helpers.
//!
//! It holds constructors for protobuf messages whose field sets are expected to
//! grow additively, so an additive contract change does not churn the test tree,
//! and [`ScopedSubscriber`], the guard for a test's default `tracing` subscriber.

use std::sync::OnceLock;
use std::time::{Duration, Instant};

use tracing::dispatcher::{self, DefaultGuard, Dispatch, WeakDispatch};

use crate::pb::lancet::v1::{Notice, NoticeCode, NoticeSeverity, QueryRagRequest};
use crate::workflow::notice;

pub fn test_query_request(query: &str, session_id: &str) -> QueryRagRequest {
    QueryRagRequest {
        query: query.to_string(),
        session_id: session_id.to_string(),
        ..Default::default()
    }
}

pub fn test_notice(code: NoticeCode, message: &str, severity: NoticeSeverity) -> Notice {
    notice(code, message, severity)
}

/// How long [`ScopedSubscriber`]'s drop waits for other threads to release the subscriber.
///
/// Another thread holds it only while tracing-core rebuilds callsite interest, which takes
/// microseconds; 10 s is far past that on a loaded CI runner and far below the job limit.
const SUBSCRIBER_RELEASE_DEADLINE: Duration = Duration::from_secs(10);

/// A do-nothing dispatcher registered for the whole test run.
///
/// While at most one dispatcher is registered, tracing-core computes a new callsite's interest
/// from the hitting thread's default subscriber alone. A test thread with no subscriber then
/// caches `Interest::never`, and another test's scoped subscriber never sees that callsite.
/// With this one always registered, tracing-core asks every live subscriber instead.
static ALWAYS_REGISTERED: OnceLock<Dispatch> = OnceLock::new();

/// The subscriber behind [`ALWAYS_REGISTERED`]: enables nothing and reports `OFF` as its max
/// level, so it never raises tracing's global level filter.
struct Disabled;

impl tracing::Subscriber for Disabled {
    fn register_callsite(
        &self,
        _: &'static tracing::Metadata<'static>,
    ) -> tracing::subscriber::Interest {
        tracing::subscriber::Interest::never()
    }

    fn max_level_hint(&self) -> Option<tracing::level_filters::LevelFilter> {
        Some(tracing::level_filters::LevelFilter::OFF)
    }

    fn enabled(&self, _: &tracing::Metadata<'_>) -> bool {
        false
    }

    fn new_span(&self, _: &tracing::span::Attributes<'_>) -> tracing::span::Id {
        tracing::span::Id::from_u64(1)
    }

    fn record(&self, _: &tracing::span::Id, _: &tracing::span::Record<'_>) {}

    fn record_follows_from(&self, _: &tracing::span::Id, _: &tracing::span::Id) {}

    fn event(&self, _: &tracing::Event<'_>) {}

    fn enter(&self, _: &tracing::span::Id) {}

    fn exit(&self, _: &tracing::span::Id) {}
}

/// This thread's default `tracing` subscriber for one test, gone before the test's providers drop.
///
/// Use it in place of `tracing::subscriber::set_default` for every test subscriber, and declare
/// any OpenTelemetry provider locals before it so they drop after it.
///
/// tracing-core briefly upgrades every live subscriber while it rebuilds callsite interest,
/// holding its global dispatcher lock. With a plain `set_default` guard another test's thread can
/// hold the last reference, so the provider inside the layer shuts down on that thread, under
/// that lock. The shutdown emits internal `tracing` events, and registering a new callsite there
/// takes the same lock again behind any waiting writer: the lib tests deadlock (#59). Dropping
/// this guard waits until the subscriber itself is gone, so the provider locals hold the last
/// reference and shut down on the test thread. Installing it also keeps a second dispatcher
/// registered for the rest of the run, so a callsite another thread hits first stays visible to
/// this subscriber.
///
/// # Panics
///
/// Dropping it panics if another thread still holds the subscriber after 10 s, so a stuck
/// thread fails the test instead of hanging the run.
pub struct ScopedSubscriber {
    guard: Option<DefaultGuard>,
    subscriber: WeakDispatch,
    deadline: Duration,
}

impl ScopedSubscriber {
    /// Sets `subscriber` as this thread's default until the returned guard drops.
    pub fn install(subscriber: impl tracing::Subscriber + Send + Sync + 'static) -> Self {
        Self::install_with_deadline(subscriber, SUBSCRIBER_RELEASE_DEADLINE)
    }

    fn install_with_deadline(
        subscriber: impl tracing::Subscriber + Send + Sync + 'static,
        deadline: Duration,
    ) -> Self {
        ALWAYS_REGISTERED.get_or_init(|| Dispatch::new(Disabled));
        let dispatch = Dispatch::new(subscriber);
        Self {
            guard: Some(dispatcher::set_default(&dispatch)),
            subscriber: dispatch.downgrade(),
            deadline,
        }
    }
}

impl Drop for ScopedSubscriber {
    fn drop(&mut self) {
        drop(self.guard.take());
        let started = Instant::now();
        while self.subscriber.upgrade().is_some() {
            if started.elapsed() > self.deadline {
                if !std::thread::panicking() {
                    panic!(
                        "ScopedSubscriber: another thread still holds this test's subscriber after {:?}",
                        self.deadline
                    );
                }
                return;
            }
            std::thread::yield_now();
        }
    }
}

mod tests {
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::time::Duration;

    use tracing_subscriber::layer::SubscriberExt;

    use super::ScopedSubscriber;

    /// Records whether the subscriber it is layered into has been dropped.
    struct DropProbe(Arc<AtomicBool>);

    impl<S: tracing::Subscriber> tracing_subscriber::Layer<S> for DropProbe {}

    impl Drop for DropProbe {
        fn drop(&mut self) {
            self.0.store(true, Ordering::SeqCst);
        }
    }

    /// #59: a subscriber another thread still holds must be gone before the guard's drop
    /// returns, so the test's provider locals drop last, on the test thread.
    #[test]
    fn scoped_subscriber_drop_waits_for_another_threads_reference() {
        let dropped = Arc::new(AtomicBool::new(false));
        let scoped = ScopedSubscriber::install(
            tracing_subscriber::Registry::default().with(DropProbe(dropped.clone())),
        );
        let foreign = tracing::dispatcher::get_default(|dispatch| dispatch.clone());
        let holder = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(200));
            drop(foreign);
        });

        drop(scoped);

        assert!(
            dropped.load(Ordering::SeqCst),
            "the subscriber outlived its guard"
        );
        holder.join().unwrap();
    }

    /// #59: a thread that never lets go fails the test instead of hanging it.
    #[test]
    fn scoped_subscriber_drop_panics_when_another_thread_never_lets_go() {
        let scoped = ScopedSubscriber::install_with_deadline(
            tracing_subscriber::Registry::default(),
            Duration::from_millis(50),
        );
        let foreign = tracing::dispatcher::get_default(|dispatch| dispatch.clone());
        let (release, released) = std::sync::mpsc::channel::<()>();
        let holder = std::thread::spawn(move || {
            let _ = released.recv();
            drop(foreign);
        });

        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(scoped)));

        release.send(()).unwrap();
        holder.join().unwrap();
        let message =
            outcome.expect_err("the guard returned while another thread held the subscriber");
        let message = message
            .downcast_ref::<String>()
            .expect("a formatted panic message");
        assert!(
            message.starts_with("ScopedSubscriber:"),
            "the panic names the guard: {message}"
        );
    }

    /// Counts the events it sees.
    struct EventCount(Arc<AtomicUsize>);

    impl<S: tracing::Subscriber> tracing_subscriber::Layer<S> for EventCount {
        fn on_event(&self, _: &tracing::Event<'_>, _: tracing_subscriber::layer::Context<'_, S>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }

    fn event_only_this_test_emits() {
        tracing::info!("scoped_subscriber_sees_a_callsite_another_thread_hit_first");
    }

    /// PR #62's flake: a callsite first hit on a thread with no subscriber must not hide it from
    /// the test thread's subscriber.
    #[test]
    fn scoped_subscriber_sees_a_callsite_another_thread_hit_first() {
        let seen = Arc::new(AtomicUsize::new(0));
        let _guard = ScopedSubscriber::install(
            tracing_subscriber::Registry::default().with(EventCount(seen.clone())),
        );

        std::thread::spawn(event_only_this_test_emits)
            .join()
            .unwrap();
        event_only_this_test_emits();

        assert_eq!(
            seen.load(Ordering::SeqCst),
            1,
            "the subscriber missed its own event"
        );
    }
}
