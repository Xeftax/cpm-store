//! Domain model for OMA CPM / NMS message storage.
//!
//! Normative references:
//! - [CPM-REST] `OMA-TS-CPM_Message_Storage_Using_RESTFul_API-V1_0-20200907-C`
//!   (resources §5.3, identification §5.4, subscriptions/sync §5.5, metadata §5.6,
//!   client procedures §6, server resources §7.3, examples Appendices C–H);
//! - [REST-NMS] `OMA-TS-REST_NetAPI_NMS-V1_0-20190528-C` (data types §5.3.2,
//!   enumerations §5.3.3, flag names Appendix H, RCS object attributes Appendix I).
//!
//! JSON field names follow the XML-to-JSON serialization rules of
//! [REST_NetAPI_Common] (camelCase element names), as used by the JSON examples
//! of the spec appendices.

// ==== Modules ====

pub mod attribute;
pub mod events;
pub mod flags;
pub mod folder;
pub mod imdn;
pub mod kind;
pub mod mapping;
pub mod object;
pub mod search;
pub mod subscription;
pub mod sync;

// ==== Public re-exports ====

pub use attribute::{Attribute, AttributeList};
pub use events::{
    ChangedFolder, ChangedObject, DeletedFolder, DeletedObject, Link, NmsEvent, NmsEventList,
    NmsEventListEnvelope, ResetBox,
};
pub use flags::{FlagList, MetadataFlag};
pub use folder::{
    Folder, FolderEnvelope, FolderList, FolderListEnvelope, FolderReferenceList,
    ObjectReferenceList, PathList, Reference, ReferenceList, TargetSourceRef,
};
pub use imdn::{Imdn, ImdnInfo, ImdnList};
pub use kind::{CpmObjectKind, Direction, MessageContext};
pub use mapping::{LocalId, ObjectId, ObjectMapping};
pub use object::{
    DraftPayloadPart, NmsObject, ObjectDraft, ObjectEnvelope, ObjectList, ObjectListEnvelope,
    ObjectUpdate, ParentRef, PayloadPartInfo,
};
pub use search::{
    BulkDelete, BulkResponse, BulkResponseList, BulkUpdate, LogicalOperator, Operation,
    RequestError, RequestErrorKind, SearchCriteria, SearchCriterion, SearchType, SelectionCriteria,
    SortCriteria, SortCriterion, SortOrder, SortType,
};
pub use subscription::{
    CallbackReference, NmsSubscription, NmsSubscriptionList, NmsSubscriptionListEnvelope,
    NmsSubscriptionUpdate, SubscriptionRequest,
};
pub use sync::SyncState;

// ==== serde helpers (XML-to-JSON conversions of [REST_NetAPI_Common]) ====

use std::collections::BTreeSet;
use std::marker::PhantomData;

use serde::Deserialize;
use serde::de::{MapAccess, SeqAccess, Visitor};

/// Visitor behind [`one_or_many`]: accepts a single element or an array.
struct OneOrMany<T>(PhantomData<T>);

impl<'de, T: Deserialize<'de>> Visitor<'de> for OneOrMany<T> {
    type Value = Vec<T>;

    fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str("a single element or an array of elements")
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Vec<T>, A::Error> {
        let mut out = Vec::with_capacity(seq.size_hint().unwrap_or(0));
        while let Some(x) = seq.next_element()? {
            out.push(x);
        }
        Ok(out)
    }

    // review: ignore duplicate-fn-bodies — Visitor trait methods required by serde; visit_map and visit_str have the same normalized shape (different deserializers), not factorizable.
    fn visit_map<A: MapAccess<'de>>(self, map: A) -> Result<Vec<T>, A::Error> {
        let v = T::deserialize(serde::de::value::MapAccessDeserializer::new(map))?;
        Ok(vec![v])
    }

    // review: ignore duplicate-fn-bodies — see visit_map.
    fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Vec<T>, E> {
        let x = T::deserialize(serde::de::value::StrDeserializer::new(v))?;
        Ok(vec![x])
    }

    fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Vec<T>, E> {
        self.visit_str(&v)
    }
}

/// Deserializes a JSON value that may be a single element or an array into a
/// `Vec` (XML-to-JSON rules of [REST_NetAPI_Common] produce a bare value for a
/// single repeated element).
pub(crate) fn one_or_many<'de, T, D>(deserializer: D) -> Result<Vec<T>, D::Error>
where
    T: Deserialize<'de>,
    D: serde::Deserializer<'de>,
{
    deserializer.deserialize_any(OneOrMany(PhantomData))
}

/// Same as [`one_or_many`] but collects into a `BTreeSet` (deduplicated and
/// ordered) — used by `FlagList` (REST-NMS §5.3.2.4: duplicates are ignored).
pub(crate) fn one_or_many_set<'de, T, D>(deserializer: D) -> Result<BTreeSet<T>, D::Error>
where
    T: Deserialize<'de> + Ord,
    D: serde::Deserializer<'de>,
{
    Ok(one_or_many(deserializer)?.into_iter().collect())
}

/// Same as [`one_or_many`] but for an optional repeated element.
pub(crate) fn one_or_many_opt<'de, T, D>(deserializer: D) -> Result<Option<Vec<T>>, D::Error>
where
    T: serde::de::DeserializeOwned,
    D: serde::Deserializer<'de>,
    D::Error: serde::de::Error,
{
    use serde::de::Error as _;

    let opt = Option::<serde_json::Value>::deserialize(deserializer)?;
    match opt {
        None => Ok(None),
        Some(serde_json::Value::Array(a)) => {
            let mut out = Vec::with_capacity(a.len());
            for x in a {
                out.push(serde_json::from_value(x).map_err(D::Error::custom)?);
            }
            Ok(Some(out))
        }
        Some(other) => Ok(Some(vec![
            serde_json::from_value(other).map_err(D::Error::custom)?,
        ])),
    }
}

/// Deserializes an xsd:boolean that XML-to-JSON conversions may render as the
/// string "true"/"false" (seen in the REST-NMS Appendix D examples).
pub(crate) fn de_bool_or_str<'de, D>(deserializer: D) -> Result<Option<bool>, D::Error>
where
    D: serde::Deserializer<'de>,
    D::Error: serde::de::Error,
{
    use serde::de::Error as _;
    match Option::<serde_json::Value>::deserialize(deserializer)? {
        None => Ok(None),
        Some(serde_json::Value::Bool(b)) => Ok(Some(b)),
        Some(serde_json::Value::String(s)) => match s.to_ascii_lowercase().as_str() {
            "true" => Ok(Some(true)),
            "false" => Ok(Some(false)),
            other => Err(D::Error::custom(format!("invalid boolean: {other}"))),
        },
        Some(_) => Err(D::Error::custom("invalid boolean")),
    }
}

/// Deserializes an xsd:unsignedLong that XML-to-JSON conversions may render as
/// a string (seen in the REST-NMS Appendix D examples).
pub(crate) fn de_u64_or_str<'de, D>(deserializer: D) -> Result<Option<u64>, D::Error>
where
    D: serde::Deserializer<'de>,
    D::Error: serde::de::Error,
{
    use serde::de::Error as _;
    match Option::<serde_json::Value>::deserialize(deserializer)? {
        None => Ok(None),
        Some(serde_json::Value::Number(n)) => n
            .as_u64()
            .map(Some)
            .ok_or_else(|| D::Error::custom("invalid unsignedLong")),
        Some(serde_json::Value::String(s)) => s
            .parse::<u64>()
            .map(Some)
            .map_err(|_| D::Error::custom(format!("invalid unsignedLong: {s}"))),
        Some(_) => Err(D::Error::custom("invalid unsignedLong")),
    }
}

/// Same as [`de_u64_or_str`] for an xsd:unsignedShort.
pub(crate) fn de_u16_or_str<'de, D>(deserializer: D) -> Result<u16, D::Error>
where
    D: serde::Deserializer<'de>,
    D::Error: serde::de::Error,
{
    use serde::de::Error as _;
    match serde_json::Value::deserialize(deserializer)? {
        serde_json::Value::Number(n) => n
            .as_u64()
            .and_then(|v: u64| u16::try_from(v).ok())
            .ok_or_else(|| D::Error::custom("invalid unsignedShort")),
        serde_json::Value::String(s) => s
            .parse::<u16>()
            .map_err(|_| D::Error::custom(format!("invalid unsignedShort: {s}"))),
        _ => Err(D::Error::custom("invalid unsignedShort")),
    }
}
