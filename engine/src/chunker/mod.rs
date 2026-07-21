use pulldown_cmark::{Event, HeadingLevel, Parser, Tag, TagEnd};
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
    static TOKENIZER: OnceLock<CoreBPE> = OnceLock::new();
    let tokenizer = TOKENIZER.get_or_init(|| {
        o200k_base().expect("the embedded o200k_base tokenizer should always initialize")
    });
    i32::try_from(tokenizer.encode_ordinary(chunk).len()).unwrap_or(i32::MAX)
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
        if count > 0 {
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
        chunks.push(Chunk {
            content: chars[start..end].iter().collect(),
            char_start: base_char_start + start,
            char_end: base_char_start + end,
            section_path: section_path.clone(),
            estimated_tokens: 0,
        });
        if end == chars.len() {
            break;
        }
        start += step;
    }
    chunks
}

#[cfg(test)]
mod tests;
