//! Golden tests: the JSON examples of the spec annexes, round-tripped through
//! the `cpm-core` models.
//!
//! PDF-first (ADR D9): when `docs/specs/pdf/<spec>.pdf` is present locally
//! (fetched with `python3 tools/specs_fetch.py`), the text is extracted with
//! `pdftotext` and the JSON examples are pulled out of the annexes. Otherwise
//! the local markdown conversion (`docs/specs/<spec>.md`) is used. When neither
//! is available (e.g. CI, where OMA documents are gitignored and not fetched),
//! the test skips gracefully.
//!
//! Extracted fixtures are written under `CARGO_TARGET_TMPDIR` (inside
//! `target/`) and are **never committed** (ADR D9: annex content is (c) OMA).
//!
//! Sources covered:
//! - [CPM-REST] annexes C–H (message object, session history folder, file
//!   transfer history, session info, group state, call log);
//! - [REST-NMS] Appendix D (JSON examples: objects, folders, subscriptions,
//!   notifications, bulk responses, ...).

use std::collections::BTreeSet;
use std::path::PathBuf;
use std::process::Command;

use cpm_core::model::*;

const CPM_REST: &str = "OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C";
const REST_NMS: &str = "OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C";

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repo root")
}

/// Which local OMA document backs the extraction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Source {
    /// Official PDF via `pdftotext` (preferred, ADR D9 PDF-first).
    Pdf,
    /// Local markdown conversion (fallback).
    Markdown,
}

/// PDF-first source text of a spec; falls back to the local markdown
/// conversion; `None` when no OMA document is available locally.
fn spec_text(spec: &str) -> Option<(String, Source)> {
    let root = repo_root();
    let pdf = root.join(format!("docs/specs/pdf/{spec}.pdf"));
    if pdf.exists() {
        let out = Command::new("pdftotext")
            .arg(&pdf)
            .arg("-")
            .output()
            .expect("pdftotext runs");
        if out.status.success() {
            return Some((
                String::from_utf8_lossy(&out.stdout).into_owned(),
                Source::Pdf,
            ));
        }
    }
    let md = root.join(format!("docs/specs/{spec}.md"));
    if md.exists() {
        return std::fs::read_to_string(md)
            .ok()
            .map(|t| (t, Source::Markdown));
    }
    None
}

/// Drops PDF page headers/footers that pdftotext interleaves with the content.
fn strip_noise(text: &str) -> String {
    text.replace('\u{000c}', "")
        .lines()
        .filter(|l| {
            let t = l.trim();
            let lower = t.to_ascii_lowercase();
            let doc_id = t.starts_with("OMA-")
                && t.chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_'));
            !(t.contains("Open Mobile Alliance")
                || t.contains("Used with the permission")
                || lower.contains("[oma-template")
                || (t.starts_with("OMA-") && (t.contains("Page ") || doc_id))
                || (t.starts_with("Page ") && t.contains('(') && t.ends_with(')')))
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// Extracts balanced-brace JSON candidates from free text (HTTP traces in the
/// annexes mix headers and JSON; only the JSON part is kept).
///
/// pdftotext artifacts repaired here: long lines are wrapped *inside* JSON
/// strings, the closing quote of a value at end of line may be dropped, and a
/// closing `]` may be lost. A raw newline inside a string is repaired with a
/// lookahead heuristic: if the next line starts a new JSON token (`"key":`,
/// `}`, `]`, `,`), the string is closed at end of line (a trailing `,` that was
/// swallowed into the string is moved back out); otherwise the newline is a
/// pure line-wrap and is dropped. Bracket mismatches auto-insert the missing
/// closer. Candidates that still do not parse as JSON are dropped by the
/// caller.
fn extract_candidates(text: &str) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    let n = chars.len();
    let mut out = Vec::new();
    let mut i = 0;
    while i < n {
        if chars[i] != '{' {
            i += 1;
            continue;
        }
        let mut stack = vec![b'{'];
        let mut in_str = false;
        let mut esc = false;
        let mut buf = String::from("{");
        let mut j = i + 1;
        while j < n && !stack.is_empty() {
            let c = chars[j];
            if in_str {
                if esc {
                    buf.push(c);
                    esc = false;
                } else if c == '\\' {
                    buf.push(c);
                    esc = true;
                } else if c == '"' {
                    buf.push(c);
                    in_str = false;
                } else if c == '\n' {
                    // Lookahead: does the next line start a new JSON token?
                    let mut k = j + 1;
                    while k < n && matches!(chars[k], '\n' | ' ' | '\t' | '\r') {
                        k += 1;
                    }
                    let starts_token = k < n && matches!(chars[k], '"' | '}' | ']' | ',');
                    if starts_token {
                        // Unterminated string at end of line: repair it.
                        if buf.ends_with(',') {
                            // The separator was swallowed into the string.
                            buf.truncate(buf.len() - 1);
                            buf.push_str("\",\n");
                        } else {
                            buf.push_str("\"\n");
                        }
                        in_str = false;
                    }
                    // else: PDF line-wrap inside the string, drop the newline.
                } else {
                    buf.push(c);
                }
            } else {
                match c {
                    '"' => {
                        buf.push(c);
                        in_str = true;
                    }
                    '{' | '[' => {
                        stack.push(c as u8);
                        buf.push(c);
                    }
                    '}' | ']' => {
                        let want = if stack.last() == Some(&b'{') {
                            '}'
                        } else {
                            ']'
                        };
                        if c != want {
                            buf.push(want); // repair a missing closer (PDF artifact)
                        }
                        buf.push(c);
                        stack.pop();
                    }
                    _ => buf.push(c),
                }
            }
            j += 1;
        }
        if stack.is_empty() {
            out.push(buf);
            i = j;
        } else {
            i += 1;
        }
    }
    out
}

/// All distinct JSON values found in `text`.
fn json_values(text: &str) -> Vec<serde_json::Value> {
    let mut seen = BTreeSet::new();
    let mut values = Vec::new();
    for cand in extract_candidates(text) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&cand) {
            if seen.insert(v.to_string()) {
                values.push(v);
            }
        }
    }
    values
}

fn fixtures_dir(spec: &str) -> PathBuf {
    let dir = PathBuf::from(env!("CARGO_TARGET_TMPDIR"))
        .join("golden")
        .join(spec);
    std::fs::create_dir_all(&dir).expect("fixture dir");
    dir
}

fn write_fixture(spec: &str, idx: usize, v: &serde_json::Value) {
    let path = fixtures_dir(spec).join(format!("example-{idx:03}.json"));
    std::fs::write(path, serde_json::to_string_pretty(v).expect("json")).expect("fixture write");
}

/// Parses `v` into `T`, serializes back, re-parses, and asserts a fixed point.
fn assert_round_trip<T>(v: &serde_json::Value) -> T
where
    T: serde::Serialize + for<'de> serde::Deserialize<'de> + PartialEq + std::fmt::Debug,
{
    let t: T = serde_json::from_value(v.clone()).expect("deserialize into model");
    let v1 = serde_json::to_value(&t).expect("serialize model");
    let t2: T = serde_json::from_value(v1.clone()).expect("re-deserialize");
    let v2 = serde_json::to_value(&t2).expect("re-serialize");
    assert_eq!(v1, v2, "round-trip must be a fixed point");
    assert_eq!(t, t2);
    t
}

/// Annexes C–H of [CPM-REST]: message/session/file-transfer/group-state/
/// call-log object examples.
#[test]
fn golden_cpm_rest_annexes_c_h_round_trip() {
    let Some((raw, source)) = spec_text(CPM_REST) else {
        eprintln!("skip: no OMA source for {CPM_REST} (run tools/specs_fetch.py)");
        return;
    };
    // Keep only the annexes region (from the last "Appendix C" heading).
    let start = raw.rmatch_indices("Appendix C").next().map(|(i, _)| i);
    let Some(start) = start else {
        eprintln!("skip: no Appendix C found");
        return;
    };
    let text = strip_noise(&raw[start..]);
    let values = json_values(&text);

    let mut objects = 0usize;
    let mut annex_c_get: Option<NmsObject> = None;
    for (i, v) in values.iter().enumerate() {
        let Some(obj) = v.get("object") else { continue };
        write_fixture(CPM_REST, i, v);
        let env = assert_round_trip::<ObjectEnvelope>(&serde_json::json!({"object": obj}));
        objects += 1;
        // The GET response of annex C: object obj542 with 2 payload parts,
        // flags \Seen+\Flagged and lastModSeq 48 (spec annex C).
        if obj.get("lastModSeq") == Some(&serde_json::json!(48)) {
            annex_c_get = Some(env.object);
        }
    }
    assert!(
        objects >= 3,
        "expected several object examples from annexes C-H, got {objects}"
    );
    // The full annex C GET response only survives extraction from the PDF
    // (the markdown conversion truncates its long JSON lines).
    if source == Source::Pdf {
        let o = annex_c_get.expect("annex C GET example (lastModSeq 48) parsed");
        assert_eq!(o.object_id().as_ref().map(ObjectId::as_str), Some("obj542"));
        assert_eq!(o.payload_part.len(), 2);
        assert_eq!(o.payload_part[0].content_type, "text/plain");
        assert_eq!(o.payload_part[1].content_type, "image/gif");
        assert!(o.flags.contains(&MetadataFlag::Seen));
        assert!(o.flags.contains(&MetadataFlag::Flagged));
        assert_eq!(o.last_mod_seq, Some(48));
        assert_eq!(o.cpm_kind(), CpmObjectKind::Message);
        assert_eq!(
            o.attributes.message_context(),
            Some(MessageContext::MultimediaMessage)
        );
        assert_eq!(o.path.as_deref(), Some("/main/conversation5/obj542"));
    }
}

/// Appendix D of [REST-NMS]: JSON examples of the resource envelopes
/// (object/objectList/folder/folderList/nmsEventList/nmsSubscription/...).
#[test]
fn golden_rest_nms_appendix_d_round_trip() {
    let Some((raw, _source)) = spec_text(REST_NMS) else {
        eprintln!("skip: no OMA source for {REST_NMS} (run tools/specs_fetch.py)");
        return;
    };
    let start = raw.rmatch_indices("Appendix D").next().map(|(i, _)| i);
    let Some(start) = start else {
        eprintln!("skip: no Appendix D found");
        return;
    };
    let text = strip_noise(&raw[start..]);
    let values = json_values(&text);

    let mut typed = 0usize;
    let mut saw_object = false;
    let mut saw_folder = false;
    for (i, v) in values.iter().enumerate() {
        let key = v
            .as_object()
            .and_then(|o| o.keys().next().cloned())
            .unwrap_or_default();
        match key.as_str() {
            "object" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<ObjectEnvelope>(v);
                saw_object = true;
                typed += 1;
            }
            "objectList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<ObjectListEnvelope>(v);
                saw_object = true;
                typed += 1;
            }
            "folder" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<FolderEnvelope>(v);
                saw_folder = true;
                typed += 1;
            }
            "folderList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<FolderListEnvelope>(v);
                saw_folder = true;
                typed += 1;
            }
            "nmsEventList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<NmsEventListEnvelope>(v);
                typed += 1;
            }
            "nmsSubscription" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<NmsSubscription>(&v["nmsSubscription"]);
                typed += 1;
            }
            "nmsSubscriptionList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<NmsSubscriptionListEnvelope>(v);
                typed += 1;
            }
            "bulkResponseList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<BulkResponseList>(&v["bulkResponseList"]);
                typed += 1;
            }
            "reference" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<Reference>(&v["reference"]);
                typed += 1;
            }
            "selectionCriteria" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<SelectionCriteria>(&v["selectionCriteria"]);
                typed += 1;
            }
            "targetSourceRef" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<TargetSourceRef>(&v["targetSourceRef"]);
                typed += 1;
            }
            "bulkUpdate" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<BulkUpdate>(&v["bulkUpdate"]);
                typed += 1;
            }
            "bulkDelete" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<BulkDelete>(&v["bulkDelete"]);
                typed += 1;
            }
            "flagList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<FlagList>(&v["flagList"]);
                typed += 1;
            }
            "imdnList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<ImdnList>(&v["imdnList"]);
                typed += 1;
            }
            "pathList" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<PathList>(&v["pathList"]);
                typed += 1;
            }
            "requestError" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<RequestError>(&v["requestError"]);
                typed += 1;
            }
            "nmsSubscriptionUpdate" => {
                write_fixture(REST_NMS, i, v);
                assert_round_trip::<NmsSubscriptionUpdate>(&v["nmsSubscriptionUpdate"]);
                typed += 1;
            }
            _ => {}
        }
    }
    assert!(
        typed >= 10,
        "expected several typed examples from REST-NMS appendix D, got {typed}"
    );
    // nmsEventList examples of appendix D are split across PDF page breaks and
    // may not survive extraction; object/folder coverage is required.
    assert!(saw_object && saw_folder);
}
