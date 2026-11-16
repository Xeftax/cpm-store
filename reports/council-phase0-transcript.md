# Council transcript — validation phase 0 cpm-store (2026-11-08)

Skill : `llm-council` (aiwithremy/claude-skills-llm-council@llm-council, installé dans
`~/neural-vault/perso/skills/llm-council`). Méthode : 5 conseillers (lenses) en parallèle →
peer review anonymisé A–E (mapping mélangé) → synthèse chairman. Tous les subagents ont
tourné sur le modèle de la session (`mistral-large-4-0-3`) ; les configs `~/.vibe/agents/council-*.toml`
(5 modèles différents) seront actives après redémarrage de Vibe.

## Question soumise au conseil

Valider (ou invalider) les décisions d'architecture de la phase 0 du projet cpm-store :
une bibliothèque Rust cliente du standard OMA CPM pour la sauvegarde/synchronisation de
conversations dans Linphone. Contexte lu : AGENTS.md, README.md, docs/architecture.md,
docs/specs.md + docs/specs/README.md, docs/roadmap.md, docs/monitoring.md.

Décisions évaluées : D1 binding REST d'abord (IMAP plus tard) · D2 licence Apache-2.0 ·
D3 lib stateless (traits de stockage exposés) · D4 workspace crates/\* MSRV 1.85 édition 2024 ·
D5 FFI C via cbindgen · D6 JSON only. Stack : reqwest 0.12, tokio 1, serde, thiserror 2,
mail-parser 0.11, wiremock 0.6, cbindgen 0.29. Phase 1 prévue : modèles cpm-core + golden
tests annexes C–H des specs.

## Réponses des 5 conseillers (mapping review : A=Expansionist, B=Contrarian, C=Outsider, D=FirstPrinciples, E=Executor)

- **Contrarian (B)** : D2/D4/D6 tiennent. D5 tient avec 2 trous (runtime tokio global OnceLock ;
  vtable C de function pointers non généré par cbindgen ; catch_unwind systématique). D3 mal
  posée : strict sync (restartToken/lastModSeq) = crash prod garanti chez l'intégrateur C non
  testé → état de synchro en mémoire dans cpm-client, stockage par défaut feature-gated.
  **D1 = risque fatal** : choix du binding par facilité client, pas par déploiement réel ;
  REST_NetAPI_NMS seule spec non embarquée → hallucination d'endpoints. Bloquer avant phase 2 :
  embarquer REST_NetAPI_NMS + QA + cible d'interop nommée, sinon inverser D1. D4 : vérifier CI
  linphone-sdk (NDK vieux builders) vs Rust 1.85/édition 2024. Annexes B, C–H à re-vérifier contre
  le PDF (tableaux aplatis) ; dédupliquer docling/ ; licence OMA « used with permission » couvre
  mal la redistribution publique. 3 blocages avant phase 1 : REST-NMS embarquée, annexes
  re-vérifiées, design état de synchro acté.
- **First Principles (D)** : le vrai problème = persistance/sync multi-appareils, pas « écrire un
  client CPM ». Verrouiller D2/D4/D5/D6. D1 tient mais REST_NetAPI_NMS non embarquée rend la règle
  « ne jamais inventer une section » inapplicable sur le transport ; wiremock prouve notre lecture,
  pas un vrai serveur → critère de sortie interop dès phases 2/3. **D3 = décision faible** :
  crash-consistency de restartToken/lastModSeq → contre-proposition : `SyncState` sérialisable en
  blob JSON stocké par l'hôte (une clé SQLite), traits = messages uniquement. Légal : vérifier la
  redistribution des copies OMA avant publication.
- **Expansionist (A)** : les 6 décisions tiennent mais sont sous-exploitées. D1 : REST = wedge, vrai
  marché = infra opérateur RCS (RCC.11) souvent IMAP → cpm-core binding-agnostic dès phase 1,
  IMAP plan B engagé. D2 : verrouiller + publier sur crates.io. D3 : sous-évaluée → crate optionnel
  avec impl de référence (SQLite/mémoire). D5 : ABI C bindable Swift/Kotlin/Python/Go, pas cxx.
  D6 : couche de négociation content-type dans cpm-nms. Publier fixtures golden (annexes C–H) en
  crate test-data publique. PDF = seule autorité normative.
- **Outsider (C)** : D2 non négociable + ajouter cargo-deny (licences + advisories) à la CI
  maintenant. D3 : le contrat des traits doit inclure l'état de synchro. D6 conforme SCR.
  Angle mort = source normative : QA markdown-vs-PDF détecte les omissions, pas les ajouts ni
  tableaux aplatis → extraire annexes B et C–H direct du PDF (pdftotext), markdown = aide de
  lecture seule. REST_NetAPI_NMS à embarquer avec même QA. D5 : figer le threading async sur papier
  avant phase 6 (contrat ABI). D1 : acceptable pour backup Linphone, garder IMAP comme vrai plan B.
- **Executor (E)** : faisable, décisions tiennent globalement. D3 : le trait de stockage doit
  inclure tokens de synchro + mapping objectId↔message local, à définir dans cpm-core dès la
  phase 1. D5 : runtime tokio possédé par cpm-ffi (créé à l'init), aucun panic à travers la
  frontière, à tester. REST_NetAPI_NMS à ingérer avant phase 2. Lundi matin : modèles cpm-core +
  golden C–H + 2 tâches (REST_NMS, trait StorageState). Risque produit : sans serveur NMS déployé,
  client sans serveur → clarifier qui pilote l'intégration Linphone.

## Peer reviews (anonymisées A–E)

- **rev-executor** : B la plus forte (3 bloqueurs actionnables) ; A angle mort (publication publique
  vs risque licensing OMA) ; manques collectifs : chiffrement/clés E2E, contradiction A vs B/D,
  contraintes mobile (NDK, mémoire/batterie).
- **rev-expansionist** : B la plus forte, D meilleure sur le design ; A angle mort (ignore spec non
  embarquée + doutes droits OMA) ; manques collectifs : confidentialité (E2E, clés, effacement/GDPR
  serveur), migration historiques Linphone, conflits multi-appareils.
- **rev-contrarian** : B la plus forte ; A angle mort maximal (crates.io + fixtures publiques =
  exposition légale ; binding-agnostic contredit le wedge D1) ; manques collectifs : D2 jamais
  analysée face au host GPLv3/AGPL (combined work, clause brevet, §13 AGPL), chiffrement/garde des
  clés, taille binaire mobile, contradiction A vs B/D non tranchée.
- **rev-outsider** : B la plus forte (seule à contester D1) ; A angle mort (spec non embarquée,
  crash-consistency, FFI, risque redistribution) ; manques collectifs : juridique AGPL
  (Apache-2.0/AGPLv3 au linkage statique), chiffrement E2E absent partout.
- **rev-first-principles** : D la plus forte (démonte le cadrage, SyncState crash-consistency) ;
  B pour le check CI/MSRV ; A plus grand angle mort ; manques collectifs : D2 vs intégration FFI dans
  linphone-sdk (linkage, obligations de source, versioning ABI C) jamais tranché.

## Verdict du chairman

### Where the Council Agrees

- D2, D4, D6 tiennent (D4 avec condition : CI linphone-sdk NDK accepte Rust 1.85/édition 2024).
- D5 tient mais le contrat FFI doit être écrit avant tout code : runtime tokio global possédé par
  cpm-ffi (OnceLock), vtable C explicite, catch_unwind à la frontière, threading figé.
- D3 mal posée : l'état de synchro (restartToken/lastModSeq, crash-consistency critique) doit entrer
  dans le contrat ; consensus sur SyncState sérialisable en blob JSON stocké par l'hôte (1 clé
  SQLite), traits = messages.
- REST_NetAPI_NMS doit être embarquée avec le même QA avant la phase 2 (4/5 conseillers).
- Annexes B et C–H ré-extraites du PDF (pdftotext), pas du markdown (QA ne voit que les omissions).
- Aucun dérivé OMA publié publiquement avant vérification des droits de redistribution.

### Where the Council Clashes

- D1 (REST d'abord) : B la juge à risque fatal (inverser si spec+QA+interop pas embarquées avant
  phase 2) ; D/C/E valident sous condition ; A valide mais se contredit (binding-agnostic vs wedge).
- Surface de publication : A veut crates.io + fixtures publiques ; B/C/D bloquent tant que les droits
  OMA ne sont pas éclaircis.
- D3 : propriétaire exact de l'état de synchro (mémoire cpm-client vs blob hôte vs traits) à trancher.

### Blind Spots the Council Caught

- Juridique : D2 jamais analysée face au host GPLv3/AGPL (compat Apache-2.0/AGPLv3 au linkage
  statique, combined work, clause brevet, §13 AGPL, versioning ABI C) — 3 peer reviews, 0 conseiller.
- Chiffrement du backup (E2E, garde des clés, effacement/GDPR serveur) — aucun conseiller.
- Contraintes mobile (taille binaire, mémoire, batterie, CI NDK vs MSRV).
- Conflits multi-appareils + migration des historiques Linphone existants.
- Risque produit : qui pilote l'intégration Linphone / serveur NMS déployé ?

### The Recommendation

Valider D2, D4, D6 telles quelles. D5 à condition d'écrire le contrat FFI avant la phase 6.
Re-scopper D3 : traits = messages + SyncState sérialisable stocké par l'hôte, mapping
objectId↔message dans cpm-core dès la phase 1. **D1 validée sous condition suspensive** : REST
d'abord tient seulement si REST_NetAPI_NMS est embarquée+QA'ée avec cible d'interop nommée avant
la phase 2, sinon inverser D1 (IMAP = plan A). Bloquer toute publication publique (crates.io,
fixtures, dérivés OMA) jusqu'à (a) droits de redistribution OMA vérifiés et (b) analyse juridique
Apache-2.0/AGPLv3 au linkage. Golden tests des annexes C–H exclusivement depuis le PDF.

### The One Thing to Do First

Embarquer REST_NetAPI_NMS dans le dépôt avec le même pipeline QA que les autres specs — 4/5
conseillers convergent là-dessus ; ça débloque le verdict définitif sur D1, le critère d'interop,
et la base normative des golden tests.
