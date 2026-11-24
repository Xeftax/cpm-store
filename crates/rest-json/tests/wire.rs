//! Wire-format tests for the `#[rest_json]` expansion: each case asserts the
//! exact JSON produced/consumed, so the lowering to `#[serde(...)]` is pinned.

use rest_json::rest_json;
use serde::{Deserialize, Serialize};

// ==== Fixtures ====

#[rest_json]
#[derive(Debug, PartialEq, Serialize, Deserialize)]
struct Plain {
    href: String,
    rel: Option<String>,
}

#[rest_json(acronyms("URL"))]
#[derive(Debug, PartialEq, Serialize, Deserialize)]
struct Acronym {
    resource_url: String,
    last_mod_seq: Option<u64>,
}

#[rest_json(default, rename(disposition_type = "type"))]
#[derive(Debug, Default, PartialEq, Serialize, Deserialize)]
struct Override {
    disposition_type: String,
    name: Option<String>,
}

#[rest_json(rename_all = "snake_case", skip_none = false)]
#[derive(Debug, PartialEq, Serialize, Deserialize)]
struct SnakeNoSkip {
    my_field: Option<u32>,
}

#[rest_json]
#[derive(Debug, PartialEq, Serialize, Deserialize)]
struct ManualWins {
    #[serde(rename = "manualKey")]
    // wire "manualKey" != camelCase "someField" — manual rename wins
    some_field: String,
    other: Option<String>,
}

#[rest_json]
#[derive(Debug, PartialEq, Serialize, Deserialize)]
enum Kind {
    FolderUrl(String),
    ResetBox,
}

// ==== Tests ====

#[test]
fn plain_camel_case_and_skip_none() {
    let v = serde_json::to_value(Plain {
        href: "h".into(),
        rel: None,
    })
    .unwrap();
    assert_eq!(v, serde_json::json!({"href": "h"})); // rel omitted when None
    let back: Plain = serde_json::from_value(serde_json::json!({"href": "h", "rel": "r"})).unwrap();
    assert_eq!(back.rel.as_deref(), Some("r"));
}

#[test]
fn acronym_stays_full_caps() {
    let a = Acronym {
        resource_url: "u".into(),
        last_mod_seq: None,
    };
    let v = serde_json::to_value(&a).unwrap();
    assert_eq!(v, serde_json::json!({"resourceURL": "u"}));
    let back: Acronym =
        serde_json::from_value(serde_json::json!({"resourceURL": "u", "lastModSeq": 3})).unwrap();
    assert_eq!(back.last_mod_seq, Some(3));
}

#[test]
fn rename_override_and_container_default() {
    let v = serde_json::to_value(Override::default()).unwrap();
    assert_eq!(v, serde_json::json!({"type": ""})); // name skipped, disposition_type -> "type"
    let back: Override = serde_json::from_value(serde_json::json!({"type": "displayed"})).unwrap();
    assert_eq!(back.disposition_type, "displayed"); // missing name filled by container default
    assert_eq!(back.name, None);
}

#[test]
fn rename_all_override_and_skip_none_disabled() {
    let v = serde_json::to_value(SnakeNoSkip { my_field: None }).unwrap();
    assert_eq!(v, serde_json::json!({"my_field": null})); // skip_none = false keeps null
}

#[test]
fn manual_field_rename_wins_over_policy() {
    let v = serde_json::to_value(ManualWins {
        some_field: "x".into(),
        other: None,
    })
    .unwrap();
    assert_eq!(v, serde_json::json!({"manualKey": "x"}));
}

#[test]
fn enum_variants_camel_case_external_tag() {
    let v = serde_json::to_value(Kind::FolderUrl("f".into())).unwrap();
    assert_eq!(v, serde_json::json!({"folderUrl": "f"}));
    let v = serde_json::to_value(Kind::ResetBox).unwrap();
    assert_eq!(v, serde_json::json!("resetBox")); // unit variant -> bare string
    let back: Kind = serde_json::from_value(serde_json::json!("resetBox")).unwrap();
    assert_eq!(back, Kind::ResetBox);
}
