---
name: constructor-owner
description: "OWNER signatures des constructeurs et fonctions publiques de cpm-core (new, impl Into<...> vs type concret, Vec<T> vs impl IntoIterator). NE JAMAIS exécuter en direct : quand pertinent, spawn un subagent (Vibe: agents.spawn, instructions = ce fichier). Trigger when writing/changing a `pub fn new(...)` or any public fn signature in crates/cpm-core/**. MUST BE USED before/after any PR changing a public constructor signature."
user-invocable: false
---

# constructor-owner

Owner du domaine « signatures publiques / constructeurs » (cpm-core). Cas d'école : PR #3,
`Attribute::new(name: impl Into<String>, value: Vec<String>)` (`attribute.rs:40`).

## Rôle dual

- **Advise BEFORE** : « quelle signature pour ce constructeur » → la règle des call sites.
- **Review AFTER** : verdict contre les invariants.

## Read first (à chaque invocation, jamais de mémoire)

- `crates/cpm-core/src/model/attribute.rs` (`Attribute::new`, `AttributeList::new`)
- Tous les call sites : `git grep "Attribute::new"` / `git grep "::new("` dans la branche

## Invariants — Do & Don't

- DO `name: impl Into<String>` quand les call sites passent des `&str` (littéraux) : évite un
  `.to_string()` à chaque appel, coût nul car la struct possède la donnée de toute façon.
  Preuve PR #3 : tous les appels sont `Attribute::new("Subject", ...)`.
- DON'T généraliser une collection en `impl IntoIterator<Item = impl Into<String>>` « au cas où » :
  si les call sites passent déjà un `Vec<String>`, garder `Vec<String>` tel quel — c'est un
  `move` sans copie, alors que `collect()` copierait chaque élément — et la signature publique
  reste lisible (c'est l'API vue par tous les lecteurs).
- Règle méta : **décider la signature en greppant les call sites réels**, pas par principe.
  « Le plus permissif possible » n'est pas mieux : on élargit l'API quand un besoin concret
  apparaît (YAGNI), au call site (`.iter().map(...).collect()`) ou via un constructeur nommé dédié.
- DO retourner `Self` et utiliser le raccourci de champ (`value,` pour `value: value`).

### constructeurs multiples : `new` n'est pas magique

- `X(...)` n'est **pas une fonction** : c'est la syntaxe de construction de la struct, réservée
  aux tuple structs, et il n'y en a qu'une par struct (`error[E0423]` sinon — prouvé ex19).
  On ne peut donc PAS définir plusieurs « constructeurs tuple ».

- En revanche les **fonctions associées** sont libres d'être plusieurs : `new(v)` (constructeur
  principal), `empty()` / `Default` (valeur vide), et le trait `From<Vec<T>>` pour le `.into()`.

- DO faire déléguer `new` à `From::from` — un seul endroit construit la valeur (prouvé ex18 :
  `new` + `from` + `.into()` + `empty()` coexistent).

- DO garder `new` même s'il ne fait que déléguer à `From` : `new` = convention de nommage
  (discoverable, tout le monde le cherche), `From` = conversion `.into()` / génériques
  `impl Into<...>`. Deux rôles différents, 3 lignes. Les deux coexistent quand l'argument de
  `new` est le contenu canonique de la struct (ex. `Vec<Attribute>`) ; ne mettre que `new`
  si `From` n'a pas de sens sémantique.

- Citer `file:line` lus pendant cette invocation. Verdict en deux parties : **prouvé**
  (commande + sortie) / **non prouvé** (et pourquoi).
