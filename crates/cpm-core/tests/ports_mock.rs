//! Integration test for the ports: an in-memory mock proves the traits are
//! implementable and **object-safe** (`&dyn ...`), as required for the future
//! C vtable of the host ports in `cpm-ffi` (ADR D5) and for test doubles.

use std::collections::HashMap;
use std::sync::Mutex;

use async_trait::async_trait;
use cpm_core::CpmError;
use cpm_core::model::*;
use cpm_core::ports::{
    FolderPage, MessageStorage, ObjectPage, StoreBackend, StoredMessage, SyncStateStore,
};

// ==== MockHost state ====
#[derive(Default)]
struct MockHost {
    messages: Mutex<HashMap<String, StoredMessage>>,
    mapping: Mutex<HashMap<String, String>>,
    sync: Mutex<Option<SyncState>>,
}

#[async_trait]
// ==== MessageStorage impl (in-memory) ====
impl MessageStorage for MockHost {
    async fn store_message(
        &self,
        local_id: &LocalId,
        object: &NmsObject,
        payload: &[u8],
    ) -> Result<(), CpmError> {
        self.messages.lock().unwrap().insert(
            local_id.as_str().to_owned(),
            StoredMessage {
                object: object.clone(),
                payload: payload.to_vec(),
            },
        );
        Ok(())
    }

    async fn get_message(&self, local_id: &LocalId) -> Result<Option<StoredMessage>, CpmError> {
        Ok(self
            .messages
            .lock()
            .unwrap()
            .get(local_id.as_str())
            .cloned())
    }

    async fn list_messages(&self) -> Result<Vec<LocalId>, CpmError> {
        Ok(self
            .messages
            .lock()
            .unwrap()
            .keys()
            .map(|k: &String| LocalId::new(k.clone()))
            .collect())
    }

    // review: ignore duplicate-fn-bodies — lock+remove+Ok(()), same normalized shape as remove_mapping (different fields).
    async fn delete_message(&self, local_id: &LocalId) -> Result<(), CpmError> {
        self.messages.lock().unwrap().remove(local_id.as_str());
        Ok(())
    }

    async fn set_mapping(&self, object_id: &ObjectId, local_id: &LocalId) -> Result<(), CpmError> {
        self.mapping
            .lock()
            .unwrap()
            .insert(object_id.as_str().to_owned(), local_id.as_str().to_owned());
        Ok(())
    }

    async fn local_id_for(&self, object_id: &ObjectId) -> Result<Option<LocalId>, CpmError> {
        Ok(self
            .mapping
            .lock()
            .unwrap()
            .get(object_id.as_str())
            .map(|s: &String| LocalId::new(s.clone())))
    }

    async fn object_id_for(&self, local_id: &LocalId) -> Result<Option<ObjectId>, CpmError> {
        Ok(self
            .mapping
            .lock()
            .unwrap()
            .iter()
            .find(|(_, v): &(&String, &String)| v.as_str() == local_id.as_str())
            .map(|(k, _): (&String, &String)| ObjectId::new(k.clone())))
    }

    // review: ignore duplicate-fn-bodies — see delete_message.
    async fn remove_mapping(&self, object_id: &ObjectId) -> Result<(), CpmError> {
        self.mapping.lock().unwrap().remove(object_id.as_str());
        Ok(())
    }
}

#[async_trait]
// ==== SyncStateStore impl ====
impl SyncStateStore for MockHost {
    async fn load(&self) -> Result<Option<SyncState>, CpmError> {
        Ok(self.sync.lock().unwrap().clone())
    }

    async fn save(&self, state: &SyncState) -> Result<(), CpmError> {
        // The host persists the serialized blob under a single key (ADR D3).
        let _json = state.to_json()?;
        *self.sync.lock().unwrap() = Some(state.clone());
        Ok(())
    }
}

/// Compile-time proof that all three ports are dyn-compatible.
#[allow(dead_code)]
fn assert_object_safe(_: &dyn StoreBackend, _: &dyn MessageStorage, _: &dyn SyncStateStore) {}

// ---- Shared stub error ----
/// Error returned by every unimplemented `NoopBackend` method (factorise the 13 identical stub bodies).
fn noop<T>() -> Result<T, CpmError> {
    Err(CpmError::NotFound("noop".into()))
}

// ==== NoopBackend: object-safety proof + stubs ====
struct NoopBackend;

#[async_trait]
// ==== StoreBackend stubs ====
impl StoreBackend for NoopBackend {
    async fn search_folders(&self, _c: &SelectionCriteria) -> Result<FolderPage, CpmError> {
        Ok(FolderPage::default())
    }
    async fn create_folder(
        &self,
        _p: ParentRef,
        _n: &str,
        _a: AttributeList,
    ) -> Result<Folder, CpmError> {
        noop()
    }
    async fn list_folders(
        &self,
        _p: Option<&Reference>,
        _c: Option<&str>,
    ) -> Result<FolderPage, CpmError> {
        Ok(FolderPage::default())
    }
    async fn get_folder(&self, _f: &Reference) -> Result<Folder, CpmError> {
        noop()
    }
    async fn update_folder(
        &self,
        _f: &Reference,
        _n: Option<&str>,
        _a: Option<AttributeList>,
    ) -> Result<Folder, CpmError> {
        noop()
    }
    async fn move_to_folder(&self, _t: &Reference, _s: &ReferenceList) -> Result<(), CpmError> {
        Ok(())
    }
    async fn copy_to_folder(&self, _t: &Reference, _s: &ReferenceList) -> Result<(), CpmError> {
        Ok(())
    }
    async fn delete_folder(&self, _f: &Reference) -> Result<(), CpmError> {
        Ok(())
    }
    async fn path_to_ref(&self, _p: &str) -> Result<Reference, CpmError> {
        noop()
    }
    async fn create_object(&self, _d: &ObjectDraft) -> Result<NmsObject, CpmError> {
        noop()
    }
    async fn bulk_create_objects(&self, _d: &[ObjectDraft]) -> Result<BulkResponseList, CpmError> {
        Ok(BulkResponseList::default())
    }
    async fn search_objects(&self, _c: &SelectionCriteria) -> Result<ObjectPage, CpmError> {
        Ok(ObjectPage::default())
    }
    async fn copy_object(&self, _t: &Reference, _s: &ReferenceList) -> Result<(), CpmError> {
        Ok(())
    }
    async fn delete_object(&self, _o: &Reference) -> Result<(), CpmError> {
        Ok(())
    }
    async fn bulk_delete_objects(&self, _s: &BulkDelete) -> Result<BulkResponseList, CpmError> {
        Ok(BulkResponseList::default())
    }
    async fn bulk_update_objects(&self, _u: &BulkUpdate) -> Result<BulkResponseList, CpmError> {
        Ok(BulkResponseList::default())
    }
    async fn get_object(&self, _o: &Reference) -> Result<NmsObject, CpmError> {
        noop()
    }
    async fn update_object(
        &self,
        _o: &Reference,
        _u: &ObjectUpdate,
    ) -> Result<NmsObject, CpmError> {
        noop()
    }
    async fn get_payload(&self, _o: &Reference) -> Result<Vec<u8>, CpmError> {
        Ok(Vec::new())
    }
    async fn get_payload_part(&self, _o: &Reference, _p: &str) -> Result<Vec<u8>, CpmError> {
        Ok(Vec::new())
    }
    async fn path_to_object_ref(&self, _p: &str) -> Result<Reference, CpmError> {
        noop()
    }
    async fn list_flags(&self, _o: &Reference) -> Result<FlagList, CpmError> {
        Ok(FlagList::new())
    }
    async fn replace_flags(&self, _o: &Reference, _f: &FlagList) -> Result<(), CpmError> {
        Ok(())
    }
    async fn set_flag(&self, _o: &Reference, _f: &MetadataFlag) -> Result<(), CpmError> {
        Ok(())
    }
    async fn unset_flag(&self, _o: &Reference, _f: &MetadataFlag) -> Result<(), CpmError> {
        Ok(())
    }
    async fn create_subscription(
        &self,
        _r: &SubscriptionRequest,
    ) -> Result<NmsSubscription, CpmError> {
        noop()
    }
    async fn list_subscriptions(&self) -> Result<NmsSubscriptionList, CpmError> {
        Ok(NmsSubscriptionList::default())
    }
    async fn get_subscription(&self, _s: &Reference) -> Result<NmsSubscription, CpmError> {
        noop()
    }
    async fn update_subscription(
        &self,
        _s: &Reference,
        _u: &NmsSubscriptionUpdate,
    ) -> Result<NmsSubscription, CpmError> {
        noop()
    }
    async fn delete_subscription(&self, _s: &Reference) -> Result<(), CpmError> {
        Ok(())
    }
    async fn poll_notifications(
        &self,
        _s: &Reference,
        _r: Option<&str>,
    ) -> Result<NmsEventList, CpmError> {
        Ok(NmsEventList::default())
    }
}

// ==== Test: ports through dyn ====
#[tokio::test]
async fn host_ports_work_through_dyn() {
    let host: &dyn MessageStorage = &MockHost::default();
    let sync: &dyn SyncStateStore = &MockHost::default();
    let _backend: &dyn StoreBackend = &NoopBackend;

    // SyncState blob round-trips through the store (single host key, ADR D3).
    assert!(sync.load().await.unwrap().is_none());
    let mut state = SyncState::new();
    state.record_progress(Some("rt-1".to_owned()), Some(7));
    sync.save(&state).await.unwrap();
    let loaded = sync.load().await.unwrap().expect("state saved");
    assert_eq!(loaded, state);
    assert_eq!(
        SyncState::from_json(&state.to_json().unwrap()).unwrap(),
        state
    );

    // Mapping objectId <-> local id (spec §5.4, ADR D3).
    let obj = NmsObject {
        resource_url: Some("http://server/nms/v1/base/tel:+1/objects/obj542".to_owned()),
        ..Default::default()
    };
    let object_id = obj.object_id().unwrap();
    let local = LocalId::new("row-42");
    host.store_message(&local, &obj, b"payload").await.unwrap();
    host.set_mapping(&object_id, &local).await.unwrap();
    assert_eq!(
        host.local_id_for(&object_id).await.unwrap(),
        Some(local.clone())
    );
    assert_eq!(
        host.object_id_for(&local).await.unwrap(),
        Some(object_id.clone())
    );
    let stored = host
        .get_message(&local)
        .await
        .unwrap()
        .expect("message stored");
    assert_eq!(stored.payload, b"payload");
    assert_eq!(host.list_messages().await.unwrap(), vec![local.clone()]);
    host.remove_mapping(&object_id).await.unwrap();
    assert_eq!(host.local_id_for(&object_id).await.unwrap(), None);
    host.delete_message(&local).await.unwrap();
    assert!(host.get_message(&local).await.unwrap().is_none());
}
