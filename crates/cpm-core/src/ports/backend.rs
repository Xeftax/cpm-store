//! `StoreBackend` — port implemented by the storage adapters (REST `cpm-nms`
//! in V1, IMAP `cpm-imap` later; ADR D1).
//!
//! Method groups mirror the server resources of spec §7.3 (REST-NMS §5.2):
//! folders §7.3.2, objects §7.3.3, flags §6.6.1.1, subscriptions/notifications
//! §7.3.1. Payloads are transported **opaque** (ADR D7).

use async_trait::async_trait;

use crate::error::CpmError;
use crate::model::{
    AttributeList, BulkDelete, BulkResponseList, BulkUpdate, FlagList, Folder, MetadataFlag,
    NmsEventList, NmsObject, NmsSubscription, NmsSubscriptionList, NmsSubscriptionUpdate,
    ObjectDraft, ObjectUpdate, ParentRef, Reference, ReferenceList, SelectionCriteria,
    SubscriptionRequest,
};

/// One page of a folder listing (cursor-based paging, REST-NMS §5.1.11).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct FolderPage {
    pub folders: Vec<Folder>,
    /// `None` means the listing is complete.
    pub cursor: Option<String>,
}

/// One page of an object search/listing (REST-NMS §5.3.2 "Type: ObjectList", §5.1.11).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ObjectPage {
    pub objects: Vec<NmsObject>,
    pub cursor: Option<String>,
    /// Set in response to a CreatedObjects search (REST-NMS §5.3.2 "Type: ObjectList").
    pub creation_cursor: Option<String>,
}

/// Client side of the CPM/NMS message store. Implemented by `cpm-nms` (REST)
/// in V1.
#[async_trait]
pub trait StoreBackend: Send + Sync {
    // --- Folders: spec §7.3.2 / §6.4.2 -------------------------------------

    /// Folder search (POST /folders/search, spec §7.3.2.1).
    async fn search_folders(&self, criteria: &SelectionCriteria) -> Result<FolderPage, CpmError>;

    /// Create a folder (POST /folders, spec §7.3.2.2).
    async fn create_folder(
        &self,
        parent: ParentRef,
        name: &str,
        attributes: AttributeList,
    ) -> Result<Folder, CpmError>;

    /// List folders under a parent (GET /folders or /folders/{id}, spec
    /// §7.3.2.3), optionally continuing from a cursor (REST-NMS §5.1.11).
    async fn list_folders(
        &self,
        parent: Option<&Reference>,
        from_cursor: Option<&str>,
    ) -> Result<FolderPage, CpmError>;

    /// Read one folder (GET /folders/{folderId}).
    async fn get_folder(&self, folder: &Reference) -> Result<Folder, CpmError>;

    /// Rename / update a folder (PUT /folders/{folderId}).
    async fn update_folder(
        &self,
        folder: &Reference,
        name: Option<&str>,
        attributes: Option<AttributeList>,
    ) -> Result<Folder, CpmError>;

    /// Move folder(s)/object(s) into a target folder (POST moveToFolder,
    /// spec §7.3.2.4).
    async fn move_to_folder(
        &self,
        target: &Reference,
        sources: &ReferenceList,
    ) -> Result<(), CpmError>;

    /// Copy folder(s)/object(s) into a target folder (POST copyToFolder,
    /// spec §7.3.2.5).
    async fn copy_to_folder(
        &self,
        target: &Reference,
        sources: &ReferenceList,
    ) -> Result<(), CpmError>;

    /// Delete a folder (DELETE /folders/{folderId}, spec §7.3.2.6).
    async fn delete_folder(&self, folder: &Reference) -> Result<(), CpmError>;

    /// Resolve a hierarchical path to its resource reference (spec §7.3.2,
    /// REST-NMS pathToId).
    async fn path_to_ref(&self, path: &str) -> Result<Reference, CpmError>;

    // --- Objects: spec §7.3.3 / §6.4.1 --------------------------------------

    /// Create an object (POST /objects, multipart root-fields + attachments,
    /// spec §7.3.3.1 and annex C).
    async fn create_object(&self, draft: &ObjectDraft) -> Result<NmsObject, CpmError>;

    /// Bulk creation (POST /objects/bulk, spec §7.3.3.2).
    async fn bulk_create_objects(
        &self,
        drafts: &[ObjectDraft],
    ) -> Result<BulkResponseList, CpmError>;

    /// Object search (POST /objects/search, spec §7.3.3.3).
    async fn search_objects(&self, criteria: &SelectionCriteria) -> Result<ObjectPage, CpmError>;

    /// Copy object(s) into a target folder (spec §7.3.3.4).
    async fn copy_object(
        &self,
        target: &Reference,
        sources: &ReferenceList,
    ) -> Result<(), CpmError>;

    /// Delete an object (DELETE /objects/{objectId}, spec §7.3.3.5).
    async fn delete_object(&self, object: &Reference) -> Result<(), CpmError>;

    /// Bulk delete (spec §7.3.3.6).
    async fn bulk_delete_objects(
        &self,
        selection: &BulkDelete,
    ) -> Result<BulkResponseList, CpmError>;

    /// Bulk update (spec §7.3.3.7, §6.6.2).
    async fn bulk_update_objects(&self, update: &BulkUpdate) -> Result<BulkResponseList, CpmError>;

    /// Read object metadata (GET /objects/{objectId}).
    async fn get_object(&self, object: &Reference) -> Result<NmsObject, CpmError>;

    /// Update an object (PUT /objects/{objectId}).
    async fn update_object(
        &self,
        object: &Reference,
        update: &ObjectUpdate,
    ) -> Result<NmsObject, CpmError>;

    /// Download the entire (opaque) payload of an object.
    async fn get_payload(&self, object: &Reference) -> Result<Vec<u8>, CpmError>;

    /// Download one payload part (`.../payloadParts/{id}`).
    async fn get_payload_part(
        &self,
        object: &Reference,
        part_href: &str,
    ) -> Result<Vec<u8>, CpmError>;

    /// Resolve an object path to its resource reference (REST-NMS pathToId,
    /// spec §7.3.3.3).
    async fn path_to_object_ref(&self, path: &str) -> Result<Reference, CpmError>;

    // --- Metadata flags: spec §5.6 / §6.6.1.1 -------------------------------

    /// List the flags of an object (GET .../flags).
    async fn list_flags(&self, object: &Reference) -> Result<FlagList, CpmError>;

    /// Replace the complete flag list (PUT .../flags).
    async fn replace_flags(&self, object: &Reference, flags: &FlagList) -> Result<(), CpmError>;

    /// Set one flag (PUT .../flags/{flag}).
    async fn set_flag(&self, object: &Reference, flag: &MetadataFlag) -> Result<(), CpmError>;

    /// Unset one flag (DELETE .../flags/{flag}).
    async fn unset_flag(&self, object: &Reference, flag: &MetadataFlag) -> Result<(), CpmError>;

    // --- Subscriptions & notifications: spec §5.5, §6.2, §7.3.1 -------------

    /// Create a subscription (POST /subscriptions, spec §7.3.1.1); a
    /// `restart_token` in the request replays past notifications
    /// (REST-NMS §5.1.4.3).
    async fn create_subscription(
        &self,
        request: &SubscriptionRequest,
    ) -> Result<NmsSubscription, CpmError>;

    /// List subscriptions (GET /subscriptions).
    async fn list_subscriptions(&self) -> Result<NmsSubscriptionList, CpmError>;

    /// Read one subscription (GET /subscriptions/{subscriptionId}).
    async fn get_subscription(&self, subscription: &Reference)
    -> Result<NmsSubscription, CpmError>;

    /// Update a subscription (PUT, REST-NMS §5.3.2.24: duration and/or
    /// restartToken).
    async fn update_subscription(
        &self,
        subscription: &Reference,
        update: &NmsSubscriptionUpdate,
    ) -> Result<NmsSubscription, CpmError>;

    /// Delete a subscription (DELETE /subscriptions/{subscriptionId}).
    async fn delete_subscription(&self, subscription: &Reference) -> Result<(), CpmError>;

    /// Long-poll notifications (GET /notifications, spec §7.3.1.2); the
    /// returned list carries `index`, `restartToken` and per-event
    /// `lastModSeq` (REST-NMS §5.1.4.3–§5.1.4.5).
    async fn poll_notifications(
        &self,
        subscription: &Reference,
        restart_token: Option<&str>,
    ) -> Result<NmsEventList, CpmError>;
}
