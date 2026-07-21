use super::{chunk_fixed_size, chunk_markdown, estimate_tokens};

#[test]
fn fixed_size_uses_character_offsets_and_bounded_overlap() {
    let chunks = chunk_fixed_size("aé🦀bcdef", 4, 2);
    assert_eq!(chunks.len(), 3);
    assert_eq!(chunks[0].content, "aé🦀b");
    assert_eq!((chunks[0].char_start, chunks[0].char_end), (0, 4));
    assert_eq!((chunks[1].char_start, chunks[1].char_end), (2, 6));
    assert_eq!((chunks[2].char_start, chunks[2].char_end), (4, 8));

    let bounded = chunk_fixed_size("abcdef", 3, 99);
    assert_eq!(bounded.len(), 4);
    assert_eq!(bounded.last().unwrap().content, "def");
}

#[test]
fn markdown_tracks_nested_heading_paths() {
    let input = "# Setup\n\nIntro\n\n## Installation\n\nInstall it.\n\n# Usage\n\nRun it.";
    let chunks = chunk_markdown(input, 100, 10);

    assert!(chunks.iter().any(|chunk| {
        chunk.content.contains("Install it")
            && chunk.section_path.as_deref() == Some("/Setup/Installation")
    }));
    assert!(chunks.iter().any(|chunk| {
        chunk.content.contains("Run it") && chunk.section_path.as_deref() == Some("/Usage")
    }));
}

#[test]
fn plain_text_falls_back_to_paragraph_and_window_splits() {
    let chunks = chunk_markdown("first paragraph\n\nabcdefghij", 5, 1);
    assert!(chunks.len() > 2);
    assert!(chunks.iter().all(|chunk| chunk.section_path.is_none()));
    assert!(chunks
        .iter()
        .all(|chunk| chunk.content.chars().count() <= 5));
}

#[test]
fn json_is_preserved_as_raw_fixed_size_text() {
    let input = r#"{"name":"lancet","enabled":true}"#;
    let chunks = chunk_fixed_size(input, 10, 2);
    assert!(chunks.len() > 1);
    assert_eq!(chunks[0].content, &input[..10]);
    assert!(chunks.iter().all(|chunk| chunk.section_path.is_none()));
}

#[test]
fn zero_target_size_returns_no_chunks() {
    assert!(chunk_fixed_size("content", 0, 0).is_empty());
    assert!(chunk_markdown("content", 0, 0).is_empty());
}

#[test]
fn token_estimation_uses_o200k_base() {
    assert_eq!(estimate_tokens("hello world"), 2);
    assert!(estimate_tokens("🦀 Rust tokenization") > 0);
}
