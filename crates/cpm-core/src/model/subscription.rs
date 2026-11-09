//! Subscriptions to storage change notifications.
//!
//! `NmsSubscription` per REST-NMS §5.3.2.22, `NmsSubscriptionList` §5.3.2.23,
//! `NmsSubscriptionUpdate` §5.3.2.24; `callbackReference` is
//! `common:CallbackReference` ([REST_NetAPI_Common], `notifyURL` +
//! optional `callbackData`). Subscriptions are part of strict synchronization
//! (spec §5.5, §6.2.1, §7.3.1.1).

use serde::{Deserialize, Serialize};

use super::search::SearchCriteria;

/// `common:CallbackReference` — client's notification endpoint and optional
/// callback data ([REST_NetAPI_Common]).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CallbackReference {
    #[serde(rename = "notifyURL")]
    pub notify_url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub callback_data: Option<String>,
}

/// `NmsSubscription` — REST-NMS §5.3.2.22 (JSON root element `nmsSubscription`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NmsSubscription {
    pub callback_reference: CallbackReference,
    /// Seconds notifications are provided for; "0"/absent = server policy.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<u32>,
    /// Filter on the storage changes to be notified about.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filter: Option<SearchCriteria>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client_correlator: Option<String>,
    #[serde(rename = "resourceURL", skip_serializing_if = "Option::is_none")]
    pub resource_url: Option<String>,
    /// Index of the next notification, meaningful only within this
    /// subscription (REST-NMS §5.3.2.22).
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::de_u64_or_str"
    )]
    pub index: Option<u64>,
    /// Box-wide restart token (REST-NMS §5.1.4.3).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub restart_token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_events: Option<u32>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::one_or_many_opt"
    )]
    pub object_attribute_names: Option<Vec<String>>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::de_bool_or_str"
    )]
    pub inline_imdn: Option<bool>,
}

/// `NmsSubscriptionList` — REST-NMS §5.3.2.23.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct NmsSubscriptionList {
    #[serde(default, deserialize_with = "super::one_or_many")]
    pub subscription: Vec<NmsSubscription>,
    #[serde(rename = "resourceURL", skip_serializing_if = "Option::is_none")]
    pub resource_url: Option<String>,
}

/// Root element `nmsSubscriptionList` wrapping an [`NmsSubscriptionList`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NmsSubscriptionListEnvelope {
    pub nms_subscription_list: NmsSubscriptionList,
}

/// `NmsSubscriptionUpdate` — REST-NMS §5.3.2.24: extend the duration and/or
/// restart the notification stream from a known `restartToken`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct NmsSubscriptionUpdate {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub restart_token: Option<String>,
}

/// Client-side subscription creation request (POST /subscriptions, spec
/// §7.3.1.1): an [`NmsSubscription`] without the server-assigned fields.
/// Setting `restart_token` on creation asks the server to replay past
/// notifications from that point (REST-NMS §5.1.4.3).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SubscriptionRequest {
    pub callback_reference: CallbackReference,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub filter: Option<SearchCriteria>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client_correlator: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub restart_token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_events: Option<u32>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::one_or_many_opt"
    )]
    pub object_attribute_names: Option<Vec<String>>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::de_bool_or_str"
    )]
    pub inline_imdn: Option<bool>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn subscription_json_round_trip() {
        let v = serde_json::json!({"nmsSubscription": {
            "callbackReference": {"notifyURL": "http://client.example.com/nms/notifications/77777",
                                  "callbackData": "abcd"},
            "duration": 3600,
            "clientCorrelator": "corr-1",
            "resourceURL": "http://server/nms/v1/base/tel:+1/subscriptions/sub1",
            "index": 1,
            "restartToken": "rt-0",
            "maxEvents": 100
        }});
        let sub: NmsSubscription = serde_json::from_value(v["nmsSubscription"].clone()).unwrap();
        assert_eq!(
            sub.callback_reference.notify_url,
            "http://client.example.com/nms/notifications/77777"
        );
        assert_eq!(sub.restart_token.as_deref(), Some("rt-0"));
        let v1 = serde_json::to_value(&sub).unwrap();
        let sub2: NmsSubscription = serde_json::from_value(v1.clone()).unwrap();
        assert_eq!(serde_json::to_value(&sub2).unwrap(), v1);
    }
}
