//! Document chunking and token estimation routines.
//!
//! Provides deterministic fixed-size and markdown-aware hierarchical chunking, a markdown-aware
//! strategy that merges paragraphs up to an o200k token budget, and token count estimation using
//! `tiktoken-rs`.

use pulldown_cmark::{Event, HeadingLevel, Parser, Tag, TagEnd};
use std::ops::Range;
use std::sync::OnceLock;
use tiktoken_rs::{o200k_base, CoreBPE};

const MAX_SPLIT_DEPTH: usize = 10;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Chunk {
    pub content: String,
    pub char_start: usize,
    pub char_end: usize,
    pub section_path: Option<String>,
    pub estimated_tokens: i32,
}

#[derive(Debug)]
struct Heading {
    byte_start: usize,
    byte_end: usize,
    level: usize,
    title: String,
}

pub fn chunk_fixed_size(text: &str, target_size: usize, overlap: usize) -> Vec<Chunk> {
    split_window(text, 0, target_size, overlap, None, 0)
}

pub fn estimate_tokens(chunk: &str) -> i32 {
    i32::try_from(token_count(chunk)).unwrap_or(i32::MAX)
}

fn tokenizer() -> &'static CoreBPE {
    static TOKENIZER: OnceLock<CoreBPE> = OnceLock::new();
    TOKENIZER.get_or_init(|| {
        o200k_base().expect("the embedded o200k_base tokenizer should always initialize")
    })
}

fn token_count(text: &str) -> usize {
    tokenizer().encode_ordinary(text).len()
}

pub fn chunk_markdown(text: &str, target_size: usize, overlap: usize) -> Vec<Chunk> {
    if text.is_empty() || target_size == 0 {
        return Vec::new();
    }

    let headings = markdown_headings(text);
    let mut hierarchy = Vec::<String>::new();
    let mut chunks = Vec::new();
    let mut cursor = 0;

    for heading in headings {
        append_region(
            &mut chunks,
            text,
            cursor,
            heading.byte_start,
            target_size,
            overlap,
            section_path(&hierarchy),
        );

        hierarchy.truncate(heading.level.saturating_sub(1));
        while hierarchy.len() < heading.level.saturating_sub(1) {
            hierarchy.push(String::new());
        }
        hierarchy.push(heading.title);

        cursor = heading.byte_start;
        let next = heading.byte_end;
        append_region(
            &mut chunks,
            text,
            cursor,
            next,
            target_size,
            overlap,
            section_path(&hierarchy),
        );
        cursor = next;
    }

    append_region(
        &mut chunks,
        text,
        cursor,
        text.len(),
        target_size,
        overlap,
        section_path(&hierarchy),
    );
    chunks
}

/// Splits markdown into chunks of whole paragraphs, sized in o200k tokens.
///
/// Each section (the text under one heading, or the text before the first heading) is chunked on
/// its own, so no chunk holds the end of one section and the start of the next. A section's heading
/// line opens its first chunk. Consecutive paragraphs merge greedily while the chunk stays within
/// `target_tokens`. A paragraph over `target_tokens` closes the open chunk and splits into windows of
/// `target_tokens` that overlap by `overlap_tokens`; the windows never merge with other paragraphs.
/// Short chunks are kept.
///
/// Every chunk holds at most `target_tokens`, except a section's first chunk: the heading attaches
/// to the first paragraph or window even when they do not fit together, so that chunk holds at most
/// `target_tokens` plus the tokens of the heading and the blank line after it.
pub fn chunk_structure_merge(
    text: &str,
    target_tokens: usize,
    overlap_tokens: usize,
) -> Vec<Chunk> {
    if text.is_empty() || target_tokens == 0 {
        return Vec::new();
    }

    let mut chunks = Vec::new();
    for section in markdown_sections(text) {
        merge_section(&mut chunks, text, &section, target_tokens, overlap_tokens);
    }
    chunks
}

/// One heading and the text up to the next heading, or the text before the first heading.
struct Section {
    heading: Option<Range<usize>>,
    body: Range<usize>,
    path: Option<String>,
}

fn markdown_sections(text: &str) -> Vec<Section> {
    let headings = markdown_headings(text);
    let mut sections = vec![Section {
        heading: None,
        body: 0..headings
            .first()
            .map_or(text.len(), |heading| heading.byte_start),
        path: None,
    }];
    let mut hierarchy = Vec::<String>::new();
    for (index, heading) in headings.iter().enumerate() {
        hierarchy.truncate(heading.level.saturating_sub(1));
        while hierarchy.len() < heading.level.saturating_sub(1) {
            hierarchy.push(String::new());
        }
        hierarchy.push(heading.title.clone());

        let body_end = headings
            .get(index + 1)
            .map_or(text.len(), |next| next.byte_start);
        sections.push(Section {
            heading: trimmed(text, heading.byte_start..heading.byte_end),
            body: heading.byte_end..body_end,
            path: section_path(&hierarchy),
        });
    }
    sections
}

fn merge_section(
    chunks: &mut Vec<Chunk>,
    text: &str,
    section: &Section,
    target_tokens: usize,
    overlap_tokens: usize,
) {
    let push = |chunks: &mut Vec<Chunk>, span: Range<usize>| {
        chunks.push(span_chunk(text, span, section.path.clone()));
    };
    // The open chunk, and whether it still holds only the section's heading.
    let mut open = section.heading.clone();
    let mut heading_only = open.is_some();

    for paragraph in paragraphs(text, section.body.clone()) {
        let oversized = token_count(&text[paragraph.clone()]) > target_tokens;
        if oversized {
            let mut windows = token_windows(text, paragraph, target_tokens, overlap_tokens);
            match open.take() {
                Some(heading) if heading_only => windows[0].start = heading.start,
                Some(span) => push(chunks, span),
                None => {}
            }
            heading_only = false;
            for window in windows {
                push(chunks, window);
            }
            continue;
        }

        open = match open.take() {
            Some(span)
                if heading_only
                    || token_count(&text[span.start..paragraph.end]) <= target_tokens =>
            {
                Some(span.start..paragraph.end)
            }
            Some(span) => {
                push(chunks, span);
                Some(paragraph)
            }
            None => Some(paragraph),
        };
        heading_only = false;
    }
    if let Some(span) = open {
        push(chunks, span);
    }
}

/// The trimmed, non-empty paragraphs of `body`, split at blank lines.
fn paragraphs(text: &str, body: Range<usize>) -> Vec<Range<usize>> {
    let mut found = Vec::new();
    let mut start = body.start;
    for piece in text[body].split_inclusive("\n\n") {
        let end = start + piece.len();
        found.extend(trimmed(text, start..end));
        start = end;
    }
    found
}

/// `span` without its leading and trailing whitespace, or `None` when nothing else is left.
fn trimmed(text: &str, span: Range<usize>) -> Option<Range<usize>> {
    let slice = &text[span.clone()];
    let content = slice.trim();
    if content.is_empty() {
        return None;
    }
    let start = span.start + (slice.len() - slice.trim_start().len());
    Some(start..start + content.len())
}

/// Windows of at most `target_tokens` over `paragraph`, each starting `overlap_tokens` before the
/// end of the previous one. Window edges fall on token boundaries, moved back to a char boundary
/// when a token ends inside a multi-byte char.
fn token_windows(
    text: &str,
    paragraph: Range<usize>,
    target_tokens: usize,
    overlap_tokens: usize,
) -> Vec<Range<usize>> {
    let slice = &text[paragraph.clone()];
    let bounds = token_bounds(slice);
    let token_total = bounds.len() - 1;
    let overlap = overlap_tokens.min(target_tokens - 1);
    let byte_at = |token: usize| {
        let mut byte = bounds[token];
        while !slice.is_char_boundary(byte) {
            byte -= 1;
        }
        byte
    };

    let mut windows = Vec::new();
    let mut first = 0;
    loop {
        let start = byte_at(first);
        let mut last = (first + target_tokens).min(token_total);
        let mut end = byte_at(last);
        // Retokenizing a window can count differently from the slice it came from, and a
        // multi-byte char can straddle the edge; shrink until the window fits and is not empty.
        while last > first + 1 && (end <= start || token_count(&slice[start..end]) > target_tokens)
        {
            last -= 1;
            end = byte_at(last);
        }
        if end <= start {
            end = start + slice[start..].chars().next().map_or(0, char::len_utf8);
        }
        windows.push(paragraph.start + start..paragraph.start + end);
        if end == slice.len() {
            return windows;
        }
        first = (last - overlap).max(first + 1);
    }
}

/// The byte offset of each token boundary in `text`, from 0 to `text.len()`.
fn token_bounds(text: &str) -> Vec<usize> {
    let tokenizer = tokenizer();
    let mut bounds = vec![0];
    for token in tokenizer.encode_ordinary(text) {
        let bytes = tokenizer
            .decode_bytes(&[token])
            .expect("a token from the encoder should always decode");
        bounds.push(bounds.last().copied().unwrap_or(0) + bytes.len());
    }
    bounds
}

fn span_chunk(text: &str, span: Range<usize>, section_path: Option<String>) -> Chunk {
    let char_start = text[..span.start].chars().count();
    Chunk {
        content: text[span.clone()].to_owned(),
        char_start,
        char_end: char_start + text[span].chars().count(),
        section_path,
        estimated_tokens: 0,
    }
}

fn markdown_headings(text: &str) -> Vec<Heading> {
    let mut headings = Vec::new();
    let mut active: Option<(usize, usize, String)> = None;

    for (event, range) in Parser::new(text).into_offset_iter() {
        match event {
            Event::Start(Tag::Heading { level, .. }) => {
                active = Some((range.start, heading_level(level), String::new()));
            }
            Event::Text(value) | Event::Code(value) => {
                if let Some((_, _, title)) = active.as_mut() {
                    title.push_str(&value);
                }
            }
            Event::End(TagEnd::Heading(_)) => {
                if let Some((byte_start, level, title)) = active.take() {
                    headings.push(Heading {
                        byte_start,
                        byte_end: range.end,
                        level,
                        title: title.trim().to_owned(),
                    });
                }
            }
            _ => {}
        }
    }
    headings
}

fn heading_level(level: HeadingLevel) -> usize {
    match level {
        HeadingLevel::H1 => 1,
        HeadingLevel::H2 => 2,
        HeadingLevel::H3 => 3,
        HeadingLevel::H4 => 4,
        HeadingLevel::H5 => 5,
        HeadingLevel::H6 => 6,
    }
}

fn section_path(hierarchy: &[String]) -> Option<String> {
    let names: Vec<_> = hierarchy
        .iter()
        .filter(|name| !name.is_empty())
        .map(String::as_str)
        .collect();
    (!names.is_empty()).then(|| format!("/{}", names.join("/")))
}

fn append_region(
    chunks: &mut Vec<Chunk>,
    text: &str,
    byte_start: usize,
    byte_end: usize,
    target_size: usize,
    overlap: usize,
    path: Option<String>,
) {
    if byte_start >= byte_end {
        return;
    }

    let region = &text[byte_start..byte_end];
    let leading_chars = text[..byte_start].chars().count();
    let mut paragraph_start = 0;

    for paragraph in region.split_inclusive("\n\n") {
        let count = paragraph.chars().count();
        if count > 0 && !paragraph.trim().is_empty() {
            chunks.extend(split_window(
                paragraph,
                leading_chars + paragraph_start,
                target_size,
                overlap,
                path.clone(),
                0,
            ));
        }
        paragraph_start += count;
    }
}

fn split_window(
    text: &str,
    base_char_start: usize,
    target_size: usize,
    overlap: usize,
    section_path: Option<String>,
    depth: usize,
) -> Vec<Chunk> {
    if text.is_empty() || target_size == 0 {
        return Vec::new();
    }

    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= target_size || depth >= MAX_SPLIT_DEPTH {
        return vec![Chunk {
            content: text.to_owned(),
            char_start: base_char_start,
            char_end: base_char_start + chars.len(),
            section_path,
            estimated_tokens: 0,
        }];
    }

    let bounded_overlap = overlap.min(target_size.saturating_sub(1));
    let step = target_size - bounded_overlap;
    let mut chunks = Vec::new();
    let mut start = 0;
    while start < chars.len() {
        let end = (start + target_size).min(chars.len());
        let chunk_content: String = chars[start..end].iter().collect();
        if !chunk_content.trim().is_empty() {
            chunks.push(Chunk {
                content: chunk_content,
                char_start: base_char_start + start,
                char_end: base_char_start + end,
                section_path: section_path.clone(),
                estimated_tokens: 0,
            });
        }
        if end == chars.len() {
            break;
        }
        start += step;
    }
    chunks
}

#[cfg(test)]
mod tests;
