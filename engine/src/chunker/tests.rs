use super::{chunk_fixed_size, chunk_markdown, chunk_structure_merge, estimate_tokens};

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

/// A paragraph of `words` copies of "lorem"; each " lorem" after the first is one o200k token.
fn lorem(words: usize) -> String {
    vec!["lorem"; words].join(" ")
}

fn tokens(text: &str) -> usize {
    usize::try_from(estimate_tokens(text)).unwrap()
}

#[test]
fn structure_merge_heading_opens_the_first_chunk_of_its_section() {
    let input = "# Setup\n\nInstall it.\n\nThen run it.";
    let chunks = chunk_structure_merge(input, 256, 25);

    assert_eq!(chunks.len(), 1);
    assert_eq!(chunks[0].content, input);
    assert_eq!(
        (chunks[0].char_start, chunks[0].char_end),
        (0, input.chars().count())
    );
    assert_eq!(chunks[0].section_path.as_deref(), Some("/Setup"));
}

#[test]
fn structure_merge_merges_paragraphs_greedily_up_to_the_target() {
    let paragraph = lorem(100);
    let pair = format!("{paragraph}\n\n{paragraph}");
    assert!(tokens(&pair) <= 256);
    assert!(tokens(&format!("{pair}\n\n{paragraph}")) > 256);
    let input = [paragraph.as_str(); 5].join("\n\n");
    let chunks = chunk_structure_merge(&input, 256, 25);

    let contents: Vec<_> = chunks.iter().map(|chunk| chunk.content.as_str()).collect();
    assert_eq!(contents, [pair.as_str(), pair.as_str(), paragraph.as_str()]);
    assert!(chunks.iter().all(|chunk| chunk.section_path.is_none()));
    for chunk in &chunks {
        let expected: String = input
            .chars()
            .skip(chunk.char_start)
            .take(chunk.char_end - chunk.char_start)
            .collect();
        assert_eq!(chunk.content, expected);
    }
}

#[test]
fn structure_merge_never_crosses_a_section_boundary() {
    let input = "Preamble.\n\n# Alpha\n\nAlpha body.\n\n## Beta\n\nBeta body.\n\n# Gamma";
    let chunks = chunk_structure_merge(input, 256, 25);

    let found: Vec<_> = chunks
        .iter()
        .map(|chunk| (chunk.content.as_str(), chunk.section_path.as_deref()))
        .collect();
    assert_eq!(
        found,
        [
            ("Preamble.", None),
            ("# Alpha\n\nAlpha body.", Some("/Alpha")),
            ("## Beta\n\nBeta body.", Some("/Alpha/Beta")),
            ("# Gamma", Some("/Gamma")),
        ]
    );
}

#[test]
fn structure_merge_splits_an_oversized_paragraph_into_overlapping_windows() {
    let long = lorem(600);
    let input = format!("Intro.\n\n{long}\n\nOutro.");
    let chunks = chunk_structure_merge(&input, 256, 25);

    assert_eq!(chunks.first().unwrap().content, "Intro.");
    assert_eq!(chunks.last().unwrap().content, "Outro.");
    let windows = &chunks[1..chunks.len() - 1];
    assert_eq!(windows.len(), 3);
    assert!(windows.iter().all(|window| tokens(&window.content) <= 256));
    assert_eq!(tokens(&windows[0].content), 256);
    assert_eq!(windows[0].char_start, "Intro.\n\n".len());
    assert_eq!(windows[2].char_end, "Intro.\n\n".len() + long.len());
    for pair in windows.windows(2) {
        let (left, right) = (&pair[0], &pair[1]);
        assert!(right.char_start < left.char_end);
        let shared = &input[right.char_start..left.char_end];
        assert_eq!(tokens(shared), 25);
    }
}

#[test]
fn structure_merge_keeps_short_chunks() {
    let input = "# A\n\nhi\n\n# B\n\nyo";
    let chunks = chunk_structure_merge(input, 256, 25);

    let contents: Vec<_> = chunks.iter().map(|chunk| chunk.content.as_str()).collect();
    assert_eq!(contents, ["# A\n\nhi", "# B\n\nyo"]);
    assert!(chunks
        .iter()
        .all(|chunk| chunk.content.chars().count() < 40));
}

/// The heading counts toward the target: when it does not fit with the section's first paragraph,
/// it closes alone. Only a heading over an oversized paragraph's first window may exceed the
/// target, by at most the tokens of the heading and the blank line after it. Every other chunk
/// stays within the target.
#[test]
fn structure_merge_only_heading_plus_first_window_may_exceed_the_target() {
    let heading = "# A heading of several words";
    let fits_alone = lorem(250);
    let oversized = lorem(600);
    let input = format!("{heading}\n\n{fits_alone}\n\n{heading}\n\n{oversized}\n\n{fits_alone}");
    let chunks = chunk_structure_merge(&input, 256, 25);

    assert_eq!(chunks[0].content, heading);
    assert_eq!(chunks[1].content, fits_alone);
    let over: Vec<_> = chunks
        .iter()
        .filter(|chunk| tokens(&chunk.content) > 256)
        .collect();
    assert_eq!(over.len(), 1);
    assert!(over[0]
        .content
        .starts_with(&format!("{heading}\n\n{}", lorem(10))));
    let count = tokens(&over[0].content);
    assert!(count <= 256 + tokens(&format!("{heading}\n\n")), "{count}");
    assert_eq!(chunks.last().unwrap().content, fits_alone);
}

#[test]
fn structure_merge_counts_multibyte_text_in_tokens() {
    let long = "數據🦀".repeat(400);
    let chunks = chunk_structure_merge(&long, 64, 8);

    assert!(chunks.len() > 1);
    assert!(chunks.iter().all(|chunk| tokens(&chunk.content) <= 64));
    assert_eq!(chunks[0].char_start, 0);
    assert_eq!(chunks.last().unwrap().char_end, long.chars().count());
}

#[test]
fn structure_merge_zero_target_returns_no_chunks() {
    assert!(chunk_structure_merge("content", 0, 0).is_empty());
    assert!(chunk_structure_merge("", 256, 25).is_empty());
}

/// `structure-aware` output on the fixtures above, pinned whole: the merge strategy must not
/// change it.
#[test]
fn structure_aware_output_on_existing_fixtures_is_unchanged() {
    type Row<'a> = (&'a str, usize, usize, Option<&'a str>);
    let assert_pinned = |input: &str, size: usize, overlap: usize, expected: &[Row]| {
        let chunks = chunk_markdown(input, size, overlap);
        let found: Vec<Row> = chunks
            .iter()
            .map(|chunk| {
                let path = chunk.section_path.as_deref();
                (
                    chunk.content.as_str(),
                    chunk.char_start,
                    chunk.char_end,
                    path,
                )
            })
            .collect();
        assert_eq!(found, expected);
    };

    assert_pinned(
        "# Setup\n\nIntro\n\n## Installation\n\nInstall it.\n\n# Usage\n\nRun it.",
        100,
        10,
        &[
            ("# Setup\n", 0, 8, Some("/Setup")),
            ("\nIntro\n\n", 8, 16, Some("/Setup")),
            ("## Installation\n", 16, 32, Some("/Setup/Installation")),
            ("\nInstall it.\n\n", 32, 46, Some("/Setup/Installation")),
            ("# Usage\n", 46, 54, Some("/Usage")),
            ("\nRun it.", 54, 62, Some("/Usage")),
        ],
    );
    assert_pinned(
        "first paragraph\n\nabcdefghij",
        5,
        1,
        &[
            ("first", 0, 5, None),
            ("t par", 4, 9, None),
            ("ragra", 8, 13, None),
            ("aph\n\n", 12, 17, None),
            ("abcde", 17, 22, None),
            ("efghi", 21, 26, None),
            ("ij", 25, 27, None),
        ],
    );
}
