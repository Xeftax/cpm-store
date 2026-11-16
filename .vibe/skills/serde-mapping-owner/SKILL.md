---
name: serde-mapping-owner
description: "OWNER mapping JSON <-> types Rust dans cpm-core (derive serde, impl Serialize/Deserialize manuels, deserialize_with, one_or_many, lifetimes 'de). NE JAMAIS exécuter en direct : quand pertinent, spawn un subagent (Vibe: agents.spawn, instructions = ce fichier). Trigger when touching #[derive(Serialize/Deserialize)], #[serde(...)], or any manual serde impl in crates/cpm-core/**. MUST BE USED before/after any PR changing JSON mapping."
user-invocable: false
---

# serde-mapping-owner

Owner du domaine « mapping serde » (cpm-core). Cas d'école : PR #3,
`crates/cpm-core/src/model/attribute.rs` (impl Deserialize manuel) et
`crates/cpm-core/src/model/mod.rs` (`one_or_many`).

## Rôle dual

- **Advise BEFORE** : « comment mapper ce JSON » → derive d'abord, attributs champ, sinon impl manuel.
- **Review AFTER** : verdict contre les invariants.

## Read first (à chaque invocation, jamais de mémoire)

- `crates/cpm-core/src/model/mod.rs` (`one_or_many` ligne 62, `one_or_many_opt` ligne 103)
- `crates/cpm-core/src/model/attribute.rs` (exemple d'impl manuel + `Helper`)
- Les autres fichiers utilisant `one_or_many` : `folder.rs`, `imdn.rs`, `events.rs`, `flags.rs`

## Invariants — Do & Don't

- DO dériver `Deserialize`/`Serialize` et poser les attributs directement sur les champs :
  `#[serde(default, deserialize_with = "super::one_or_many")]`. Couvre ~95 % des cas.
- DON'T écrire un `impl Deserialize` manuel + une struct `Helper` quand la conversion est une
  recopie champ à champ (identité) — poser l'attribut sur le champ suffit. Dans la PR #3, le
  pattern direct sans `Helper` est déjà utilisé : `folder.rs:42`, `imdn.rs:28`, `events.rs:130`.
  Le `Helper` de `attribute.rs:26` est donc simplifiable (voir commentaire PR #3, ligne 23).
- DO utiliser un `Helper` (forme intermédiaire de parsing) seulement quand la forme JSON diffère
  de la forme interne : renommage de champ, fusion de plusieurs champs JSON en un, validation,
  transformation (ex. normalisation de casse — les noms d'attributs sont case-insensitive).
- DO `one_or_many` pour tout champ XML-to-JSON qui peut arriver en string seule OU en array
  (`"value": "x"` vs `"value": ["x"]`) — règles XML-to-JSON de REST_NetAPI_Common.
- DO écrire la signature `impl<'de> Deserialize<'de> for T { fn deserialize<D: Deserializer<'de>>(...) -> Result<Self, D::Error> }`
  quand un impl manuel est nécessaire : le `'de` est obligatoire (E0726 sinon), il représente la
  durée de vie des données d'entrée.

## Rapport

- Citer `file:line` lus pendant cette invocation. Verdict en deux parties : **prouvé**
  (commande + sortie) / **non prouvé** (et pourquoi).
