# Conformance — SCR checklist (client)

Source: [CPM-REST] annex B (`docs/specs.md`). The client SCRs of the CPM Message
Storage are inherited from the client SCRs of [REST-NMS]; the items below
are the client capabilities required by [CPM-REST] §5–§7. Every item must end up
covered by a test ("Test" column).

Legend: ☐ to do · ◐ partial · ☑ done

## Authentication (spec §5.2.1)

- [ ] Bearer JWT (OIDC/OAuth2 ID Token) sent on every request — `CPM-REST §5.2.1.1` — Test:
- [ ] Basic/Digest (preconfigured credentials) — `§5.2.1.3` — Test:
- [ ] GBA (bootstrapping token) — optional — `§5.2.1.2` — Test:

## Folders (spec §7.3.2)

- [ ] List folders — `§7.3.2.3` — Test:
- [ ] Create a folder (POST) — `§7.3.2.2` — Test:
- [ ] Read a folder (GET) — Test:
- [ ] Rename a folder (PUT) — Test:
- [ ] Delete a folder (DELETE) — `§7.3.2.6` — Test:
- [ ] Search folders (POST search, roots) — `§7.3.2.1` — Test:
- [ ] path → id (GET/POST) — Test:
- [ ] Copy objects/folder to a target folder (POST copyToFolder) — `§7.3.2.5` — Test:
- [ ] Move objects/folder to a target folder (POST moveToFolder) — `§7.3.2.4` — Test:

## Objects (spec §6.4, §7.3.3)

- [ ] Create an object (POST `/objects`, multipart root-fields + attachments) — `§7.3.3.1`, annex C — Test:
- [ ] Read object metadata (GET) — Test:
- [ ] Update an object (PUT) — Test:
- [ ] Delete an object (DELETE) — `§7.3.3.5` — Test:
- [ ] Bulk create — `§7.3.3.2` — Test:
- [ ] Bulk update — `§7.3.3.7` — Test:
- [ ] Bulk delete — `§7.3.3.6` — Test:
- [ ] Search objects (POST search criteria) — `§7.3.3.3` — Test:
- [ ] path/location → objectId (GET/POST) — `§7.3.3.3` — Test:
- [ ] Read the full payload of an object (GET) — Test:
- [ ] Read an individual payload part (GET `.../payloadParts/{id}`) — Test:
- [ ] Copy an object to a target folder — `§7.3.3.4` — Test:

## Metadata flags (spec §5.6)

- [ ] List an object's flags (GET `.../flags`) — Test:
- [ ] Replace the full set of flags (PUT) — Test:
- [ ] Test/add/delete an individual flag (GET/PUT/DELETE `.../flags/{flag}`) — Test:
- [x] Supported flags: `\Seen`, `\Answered`, `\Flagged`, `\Deleted`, `\Draft`, `\Recent`, `$Forwarded`, `\read-report-sent`, `Archived` — `§5.6` — Test: `cpm-core::model::flags::tests::all_spec_flags_round_trip` (+ `flag_names_are_case_insensitive`, `non_cpm_template_flags_become_keywords`, `flag_list_json_shape`); golden `golden_cpm_rest_annexes_c_h_round_trip` (annex C: `\Seen`+`\Flagged` on object obj542)

## Subscriptions / notifications (spec §5.5, §7.3.1)

- [ ] Create a subscription (POST) — `§7.3.1.1` — Test:
- [ ] Create a subscription + initial sync (POST) — Test:
- [ ] List subscriptions (GET) — Test:
- [ ] Read/update/delete a subscription — Test:
- [ ] Receive the notifications (GET, long-poll) with `lastModSeq` and `restartToken` — `§7.3.1.2` — Test:

## Synchronization (spec §6.3) — MUST: strict sync only

- [ ] Strict synchronization with a per-user folder token — `§6.3.2` — Test:
- [ ] First-time sync: download existing + upload missing local — `§6.3.3.1` — Test:
- [ ] Steady-state sync: wait for notifications + correlate with local cache — `§6.3.3.2` — Test:
- [ ] Escape procedure (fallback) to a first-time sync on unrecoverable error — `§6.3.3.2 NOTE` — Test:
- [ ] Do NOT attempt the simplified synchronization — `§6.3.1` — Test:

## Formats

- [ ] JSON only (Mandatory server-side; XML not supported) — annex B — Test:
