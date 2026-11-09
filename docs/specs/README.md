# Specs OMA embarquées

Ce dossier contient les copies **markdown** des 7 spécifications OMA utilisées par
ce projet (6 specs CPM V2_2 + `OMA-TS-REST_NetAPI_NMS`, base du binding REST).
Les PDF officiels publiés sur https://www.openmobilealliance.org/release/ restent
la **référence normative** ; ces copies servent de contexte de lecture (humain et
LLM). Chaque `<spec>.md` est accompagné de son dossier `<spec>_artifacts/` (images
extraites, référencées en chemins relatifs).

## Provenance

- **PDF officiels** : Open Mobile Alliance —
  - CPM V2_2 : https://www.openmobilealliance.org/release/CPM/V2_2-20200907-C/
  - REST_NetAPI_NMS : https://www.openmobilealliance.org/release/REST_NETAPI_NMS/V1_0-20190528-C/
    (© Open Mobile Alliance Ltd., publiés sous les termes indiqués dans chaque document).
- **Conversion PDF → markdown : faite dans ce repo**, le 2026-11-08, avec
  [docling](https://github.com/docling-project/docling)
  (`docling convert <pdf> --to md --image-export-mode referenced`), hiérarchie de
  titres et tableaux mieux préservés que la conversion tierce.
  Les anciennes copies markdown copiées telles quelles depuis le dépôt tiers
  [Xeftax/cpm-rag](https://github.com/Xeftax/cpm-rag) ont été **remplacées** le
  2026-11-08 (elles restent dans l'historique git et dans ce dépôt tiers).
- Les PDF eux-mêmes ne sont **pas** commités (voir section « Publication » ci-dessous).

## Publication (repo public open source)

Le **code** de cpm-store est publiable librement (Apache-2.0, œuvre originale).
En revanche les documents OMA sont sous **copyright OMA** : les termes
(« Used with the permission of the Open Mobile Alliance », Use Agreement
omaspecworks.org) autorisent l'usage **interne/éducatif uniquement** — pas la
redistribution. Sont donc **gitignorés et jamais commités** (région
`oma-specs-not-redistributable` de `.gitignore`) :

- `docs/specs/pdf/` (les PDF téléchargés),
- `docs/specs/OMA-*.md` et `docs/specs/*_artifacts/` (conversions markdown + images),
- les **fixtures golden extraites des annexes** des specs (elles font partie du
  document OMA) — les tests doivent les générer au moment du test depuis les PDF
  locaux, pas les embarquer.

Pour travailler en local ou en CI : `python3 tools/specs_fetch.py --convert --qa`
télécharge les 7 PDF officiels depuis openmobilealliance.org, les convertit
(docling) et lance la QA. Citer des numéros de section ou de courtes citations dans
nos propres docs reste OK ; copier le contenu des specs, non.

- Une conversion par **Mistral OCR** reste possible via `tools/spec_ingest.py`
  quand `MISTRAL_API_KEY` est exportée dans le shell.

## Vérification qualité (2026-11-08, relancée après restructuration)

Outil : `tools/specs_qa.py` (rapport : `reports/specs-qa.json`).
Méthode : texte des PDF via `pdftotext`, comparaison avec les markdown après
normalisation (minuscules, non-alphanum supprimé — tolère retours à la ligne,
césures, casse).

Résultats sur les 7 markdown canoniques :

- **Chaînes normatives clés** (identifiants SCR, tokens `restartToken`/`lastModSeq`,
  URLs d'exemple `/nms/v1/...`, sections `5.2.1`/`6.3.2`, types d'objets CPM, etc.) :
  **54/54 présentes à la fois dans le PDF et dans le markdown** (12–16 clés par spec).
- **Échantillon aléatoire de 300 phrases par spec** : 67–79 % de match exact.
  Les phrases non matchées sont des artefacts de mise en page PDF (en-têtes, pieds de
  page « Used with the permission of the Open Mobile Alliance », numéros de page,
  phrases coupées par saut de page).

Limites connues de cette QA : elle détecte les **omissions**, pas les ajouts ni les
tableaux aplatis par une conversion. **Pour les annexes normatives** (SCR annexe B,
exemples JSON/MIME annexes C–H, qui serviront de fixtures golden) : **extraire
directement depuis le PDF avec `pdftotext`**, le markdown servant d'aide de lecture.
En cas de doute, le PDF officiel fait autorité.
