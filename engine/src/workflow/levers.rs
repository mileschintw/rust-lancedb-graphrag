//! The set of quality levers a query request switches on (06.3.6 D-136).
//!
//! A request names its levers as raw `i32` wire values. [`LeverSet::try_from_wire`] is the single
//! place those integers become typed: it refuses an unknown value, `LEVER_UNSPECIFIED`, a negative
//! value and a duplicate, so a direct gRPC caller cannot reach the workflow with a lever this build
//! does not know. The admitted set is stored as a bit mask, one bit per enum number, which makes
//! [`LeverSet::to_wire`] canonical (ascending enum number) whatever order the client sent.
//!
//! An empty set is today's request: the snapshot echo is then an empty list, which proto3 writes as
//! zero bytes.

use std::fmt;

use crate::pb::lancet::v1::Lever;

/// Every lever this build declares, in ascending enum number.
const DECLARED: [Lever; 4] = [
    Lever::Rerank,
    Lever::EvidenceMetadata,
    Lever::BinaryAnswerFormat,
    Lever::GraphV2,
];

/// The name a lever carries on the gateway wire and in `[engine.levers] defaults`.
///
/// `Lever::Unspecified` is not a lever and has no name.
pub(crate) fn wire_name(lever: Lever) -> &'static str {
    match lever {
        Lever::Unspecified => "unspecified",
        Lever::Rerank => "rerank",
        Lever::EvidenceMetadata => "evidence_metadata",
        Lever::BinaryAnswerFormat => "binary_answer_format",
        Lever::GraphV2 => "graph_v2",
    }
}

/// The admitted quality levers of one request, held as a bit mask.
///
/// Bit `n - 1` is set when the lever with enum number `n` is in the set. The default value is the
/// empty set, which is the request that names no lever.
///
/// # Examples
///
/// ```ignore
/// let set = LeverSet::try_from_wire(&[3, 1])?;
/// assert_eq!(set.to_wire(), vec![1, 3]);
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct LeverSet(u8);

/// The ways a raw `levers` list can be refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LeverErrorKind {
    Unknown,
    Unspecified,
    Negative,
    Duplicate,
}

/// A raw `levers` list was refused; carries the kind of refusal and the offending value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LeverError {
    kind: LeverErrorKind,
    value: i32,
}

impl LeverError {
    fn new(kind: LeverErrorKind, value: i32) -> Self {
        Self { kind, value }
    }

    /// Whether the value is a positive number this build does not declare.
    pub fn is_unknown(&self) -> bool {
        self.kind == LeverErrorKind::Unknown
    }

    /// Whether the value is `LEVER_UNSPECIFIED`, which is never a valid member.
    pub fn is_unspecified(&self) -> bool {
        self.kind == LeverErrorKind::Unspecified
    }

    /// Whether the value is negative.
    pub fn is_negative(&self) -> bool {
        self.kind == LeverErrorKind::Negative
    }

    /// Whether the value appears more than once in the list.
    pub fn is_duplicate(&self) -> bool {
        self.kind == LeverErrorKind::Duplicate
    }

    /// The offending raw wire value.
    pub fn value(&self) -> i32 {
        self.value
    }
}

impl fmt::Display for LeverError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let reason = match self.kind {
            LeverErrorKind::Unknown => "is not a lever this build declares",
            LeverErrorKind::Unspecified => "is LEVER_UNSPECIFIED, which is not a valid lever",
            LeverErrorKind::Negative => "is negative",
            LeverErrorKind::Duplicate => "appears more than once",
        };
        write!(f, "lever value {} {reason}", self.value)
    }
}

impl std::error::Error for LeverError {}

/// A configured lever name was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LeverNameError {
    name: String,
    reason: &'static str,
}

impl LeverNameError {
    /// The offending name as configured.
    pub fn name(&self) -> &str {
        &self.name
    }
}

impl fmt::Display for LeverNameError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "lever name {:?} {}", self.name, self.reason)
    }
}

impl std::error::Error for LeverNameError {}

impl LeverSet {
    /// Parses the raw `levers` wire list of a request.
    ///
    /// # Errors
    ///
    /// Returns a [`LeverError`] for the first value that is negative, `0`, not a declared lever,
    /// or a repeat of an earlier value. The list is read as raw integers because prost keeps an
    /// unknown enum value as it arrived.
    pub fn try_from_wire(raw: &[i32]) -> Result<Self, LeverError> {
        let mut bits = 0_u8;
        for &value in raw {
            if value < 0 {
                return Err(LeverError::new(LeverErrorKind::Negative, value));
            }
            let lever = match Lever::try_from(value) {
                Ok(Lever::Unspecified) => {
                    return Err(LeverError::new(LeverErrorKind::Unspecified, value));
                }
                Ok(lever) => lever,
                Err(_) => return Err(LeverError::new(LeverErrorKind::Unknown, value)),
            };
            let bit = Self::bit(lever);
            if bits & bit != 0 {
                return Err(LeverError::new(LeverErrorKind::Duplicate, value));
            }
            bits |= bit;
        }
        Ok(Self(bits))
    }

    /// Parses the lever names of the `[engine.levers] defaults` setting.
    ///
    /// # Errors
    ///
    /// Returns a [`LeverNameError`] for the first name that is blank, not a declared wire name,
    /// a repeat of an earlier name, or out of canonical order (ascending enum number).
    pub fn try_from_names(names: &[String]) -> Result<Self, LeverNameError> {
        let refuse = |name: &String, reason| LeverNameError {
            name: name.clone(),
            reason,
        };
        let mut bits = 0_u8;
        let mut previous = 0_i32;
        for name in names {
            let Some(lever) = DECLARED
                .into_iter()
                .find(|lever| wire_name(*lever) == name.as_str())
            else {
                return Err(refuse(name, "is not a lever this build declares"));
            };
            let bit = Self::bit(lever);
            if bits & bit != 0 {
                return Err(refuse(name, "appears more than once"));
            }
            if (lever as i32) < previous {
                return Err(refuse(name, "is out of canonical order (ascending enum number)"));
            }
            previous = lever as i32;
            bits |= bit;
        }
        Ok(Self(bits))
    }

    /// Whether `lever` is in the set.
    pub fn contains(&self, lever: Lever) -> bool {
        lever != Lever::Unspecified && self.0 & Self::bit(lever) != 0
    }

    /// Whether the set names no lever, which is today's request.
    pub fn is_empty(&self) -> bool {
        self.0 == 0
    }

    /// The set as wire values in ascending enum number, the snapshot echo.
    pub fn to_wire(&self) -> Vec<i32> {
        DECLARED
            .iter()
            .filter(|lever| self.contains(**lever))
            .map(|lever| *lever as i32)
            .collect()
    }

    /// The set as typed levers in ascending enum number.
    pub fn iter(&self) -> impl Iterator<Item = Lever> + '_ {
        DECLARED.into_iter().filter(|lever| self.contains(*lever))
    }

    fn bit(lever: Lever) -> u8 {
        1_u8 << (lever as i32 - 1)
    }
}
