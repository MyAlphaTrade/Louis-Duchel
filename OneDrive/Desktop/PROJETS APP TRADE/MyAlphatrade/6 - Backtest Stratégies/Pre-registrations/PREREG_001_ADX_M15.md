# PREREG_001 — ADX(M15) et temps de comblement des gaps de session cash du Nasdaq

**Version 0.2 — candidate à l'enregistrement.** Ce fichier devient le pré-enregistrement au moment où il est commité après validation explicite (D6). La date d'enregistrement est celle de ce commit (message de commit et tag annoté `prereg-001-adx-m15`). Un fichier ne pouvant pas contenir son propre hash, le SHA-256 du fichier figure dans `PREREG_001_ADX_M15.md.sha256`, dans le message de commit et dans la validation de Louis.

Ce texte fixe, avant qu'aucune donnée prospective n'existe et avant qu'aucune issue prospective n'ait été consultée, ce qui sera testé, comment, et à quel moment. Il remplace la version 0.1 (SHA-256 `dc683998…`, jamais enregistrée, caduque).

## 0. Statut, preuve et règles d'amendement

- Après enregistrement, **ce texte n'est plus édité**. Toute modification est un amendement daté dans un nouveau fichier `PREREG_001_amendement_NN.md`, justifié indépendamment de tout résultat. Un défaut de spécification révélé après enregistrement se traite par amendement, jamais par réécriture.
- Hiérarchie de la preuve : **contenu du fichier → commit → tag annoté → push externe**. Le hash probant est celui du contenu tel que Git le stocke (fins de ligne LF) : `git show <commit>:"6 - Backtest Stratégies/Pre-registrations/PREREG_001_ADX_M15.md" | sha256sum`. Toute présentation HTML n'a aucune valeur probante.
- **Séquence d'enregistrement :** validation explicite de Louis → revérification de l'attestation (§ 9) → commit (accord explicite) → tag annoté (accord explicite) → push de la branche et du tag (accord explicite, séparé). Aucune issue prospective n'est consultée avant le commit.
- **Ordre du code (D4.9) :** le code d'analyse (H1, D4, D7) est commité **avant** ce fichier et cité au § 11. Le commit d'enregistrement ne contient que ce fichier et son `.sha256`.
- **Aucun import du protocole (D5) avant le commit d'enregistrement**, faute de quoi l'attestation du § 9 pourrait devenir fausse.
- Limite assumée : la date d'un commit est déclarée par la machine locale ; l'horodatage extérieur est apporté par le push sur GitHub.

## 1. Origine de l'hypothèse (transparence)

L'expérience 1 a comparé 25 sous-groupes pré-déclarés. **ADX(M15) a été retenu après lecture des résultats Discovery et OOS** ; l'OOS historique est donc consommé pour cette hypothèse. 11 sous-groupes comparables sur 18 vont dans le même sens dans les deux échantillons (61 %), ce qui est compatible avec le hasard. Une hypothèse choisie parce qu'elle ressortait le mieux est exposée à la malédiction du vainqueur : l'effet réel est probablement plus faible que celui observé. La direction observée (range plus rapide que tendance) est consignée pour transparence ; **elle n'est pas imposée à H1** (test bilatéral).

Aucun résultat historique utilisé pour calibrer ou diagnostiquer ce protocole (D1–D7) ne constitue une validation de H1.

## 2. Hypothèse H1 (bilatérale)

- **H1.** Parmi les gaps de session cash du Nasdaq (US Tech 100) dont `T_event ≥ 2026-09-17T00:00:00Z` (début prospectif), le temps de comblement diffère entre les gaps dont le contexte ADX(14) M15 est ≤ 20 (« range ») et ceux dont il est ≥ 25 (« tendance »).
- **H0.** Les RMST à τ (§ 4) sont égaux : Δ = 0.
- **Catégories figées :** range = ADX ≤ 20 (20 inclus) ; tendance = ADX ≥ 25 (25 inclus) ; 20 < ADX < 25 = « intermédiaire », hors test. Ce sont les catégories descriptives de l'expérience 1, jamais optimisées. Ni la période ADX (14), ni les seuils, ni l'horizon ne sont optimisés.
- **Contexte :** ADX de Wilder, période 14, timeframe M15, valeur de la dernière bougie M15 **clôturée** avant `T_event` (règle causale : bougie dont l'ouverture est ≤ `T_event` − 15 min). Code `relations_experiment.py`.
- Le « début prospectif » (`T_event ≥ 2026-09-17T00:00:00Z`) est nommé ainsi pour ne pas le confondre avec l'OOS historique du 2025-12-01, déjà consommé.

## 3. Population et éligibilité

- **Événement :** gap de session cash, identique à l'expérience 1 (`compute_cash_session_gaps`, 9h30 ET, tolérance 60 min).
- **Outcome :** `find_fill_time`, horizon de **2000 bougies M15 ≈ 30 jours calendaires** (médiane mesurée 30,2 j ; min 29,7 ; max 34,4).
- **Horizon réel (définition) :** durée entre `T_event` et l'horodatage de la dernière bougie de sa fenêtre de 2000 bougies.
- **Éligibilité :** une observation est éligible **uniquement quand son horizon complet est observé** dans les données (2000 bougies M15 à partir de `T_event`), qu'elle soit comblée ou non. Compter d'abord les gaps déjà comblés biaiserait l'échantillon vers les comblements rapides.
- **Statuts, séparés :** comblé (avec durée) ; jamais comblé après horizon complet ; censuré par fin de dataset (inéligible). Aucune durée infinie n'est imputée.
- **Exclusions**, comptées séparément et jamais assimilées à des non-comblés : contexte ADX(M15) indisponible ; horizon non mûr.
- **Événements non matures à la référence historique (D4.2) :** les 22 événements dont `T_event` est postérieur au 2026-08-14 et antérieur au début prospectif ne sont ni exploitables comme historiques (horizon incomplet : issue censurée par la fin des données) ni prospectifs (`T_event` < 2026-09-17, début d'issue déjà visible dans les données de référence). Ils sont **exclus de D4 et de H1, définitivement**, même quand un import futur complétera leur horizon. Liste (`T_event|groupe`, SHA-256 `3db36b76c22c6f6328b1eb78c2e44502b8b8801842b06557e1cfe40be96fd972`) :

```
2026-08-17T13:30:00Z|tendance
2026-08-18T13:30:00Z|tendance
2026-08-19T13:30:00Z|intermediaire
2026-08-20T13:30:00Z|tendance
2026-08-21T13:30:00Z|tendance
2026-08-24T13:30:00Z|intermediaire
2026-08-25T13:30:00Z|tendance
2026-08-26T13:30:00Z|range
2026-08-27T13:30:00Z|range
2026-08-28T13:30:00Z|range
2026-08-31T13:30:00Z|range
2026-09-01T13:30:00Z|tendance
2026-09-02T13:30:00Z|intermediaire
2026-09-03T13:30:00Z|range
2026-09-04T13:30:00Z|intermediaire
2026-09-07T13:30:00Z|tendance
2026-09-08T13:30:00Z|intermediaire
2026-09-09T13:30:00Z|tendance
2026-09-10T13:30:00Z|tendance
2026-09-11T13:30:00Z|tendance
2026-09-14T13:30:00Z|tendance
2026-09-15T13:30:00Z|tendance
```

## 4. D1 — Critère principal

**D1 — Critère principal :** les trois statuts restent séparés : comblé + durée, jamais comblé après horizon complet, censuré par fin de dataset (inéligible). Aucune durée infinie n'est imputée. Un temps commun **τ** est défini au déclenchement comme le plus petit horizon réel en minutes parmi les observations éligibles, calculé à partir des bougies uniquement. Le critère principal est la différence de RMST à τ entre ADX(M15) ≤ 20 et ADX(M15) ≥ 25, avec IC bootstrap bilatéral à 95 %. L'hypothèse est soutenue si cet IC exclut 0. Le test log-rank bilatéral à α = 0,05 est une analyse de sensibilité. Les taux de comblement à τ, médianes des comblés, médiane Kaplan-Meier si estimable, effectifs et courbes de comblement sont rapportés sans poids de décision.

- **Règle de τ (verrouillée) :** le groupe intermédiaire n'entre pas dans le calcul de τ. τ est calculé uniquement sur les observations éligibles des groupes range et tendance ; une observation d'un autre groupe ou sans horizon complet est refusée, jamais ignorée en silence. Le τ prospectif est calculé au déclenchement ; le τ historique des § 7 et 10 (τ_hist = 42765 min avec les données de référence) est un objet distinct.
- **Clause de lecture (acceptée) :** le critère RMST répond uniquement à la question « le temps moyen plafonné à τ diffère-t-il entre les deux contextes ? » ; il ne permet pas, à lui seul, d'attribuer cette différence à la vitesse typique ou à la traîne.
- **Décomposition descriptive de ΔRMST (acceptée, sans poids de décision) :** contribution des observations non comblées à τ ; contribution des observations comblées avant τ ; médiane des temps parmi les comblés.
- **Formulation de H1 :** « le temps de comblement des gaps diffère entre les contextes ADX(M15) ≤ 20 et ≥ 25 » ; la direction observée en expérience 1 reste une motivation historique, pas une définition.
- **Libellé du verdict (amendement) :** IC principal excluant 0 → « soutenue » ; IC contenant 0 → **« non concluante »** (jamais « non soutenue »), avec la largeur de l'IC rapportée. Ce n'est pas la preuve d'une absence d'effet.

## 5. D2 — Bootstrap

**D2 — Bootstrap.** L'IC principal (D1) est un bootstrap percentile bilatéral à 95 %, 10 000 rééchantillonnages avec remise, stratifié par groupe (tailles observées conservées), graine maître 20260918. Statistique : Δ = RMST_range(τ) − RMST_tendance(τ), avec RMST_g(τ) = ∫₀^τ S_g(t) dt, où S_g est la courbe de survie « non comblé à t » du groupe g ; les observations non comblées à τ sont traitées comme censurées à τ. τ est fixé une seule fois au déclenchement et n'est pas recalculé par rééchantillon. Δ < 0 signifie que le temps moyen restreint jusqu'au comblement est plus court dans le groupe range ; l'hypothèse reste bilatérale.

**Sensibilité, sans poids de décision :** même statistique avec bootstrap par blocs de semaines ISO (semaines rééchantillonnées avec remise ; rééchantillons dont un groupe est vide écartés et comptés). Si l'IC par blocs inclut 0 alors que l'IC principal l'exclut, le résultat est rapporté « soutenu, non robuste à la dépendance intra-semaine » ; le verdict de H1 reste celui du critère principal (D1).

**Justification empirique, sans valeur de preuve :** sur l'historique, rapport de largeurs des IC = 1,03 ; autocorrélation lag-1 = 0,03 (min(T, τ)) et 0,09 (non-comblé). Cela justifie le choix du principal mais ne prouve pas l'indépendance des observations futures.

**Note de vérification :** aucune censure n'existant avant τ, RMST_g(τ) est égal à la moyenne des min(Tᵢ, τ) ; l'égalité est testée.

**Amendement D2-flux (verrouillé).** Chaque analyse bootstrap reçoit un flux déterministe distinct : `random.Random(int.from_bytes(SHA-256(UTF-8("{graine_maître}|{étiquette}")), "big"))`, graine maître 20260918. Étiquettes explicites, uniques et préfixées par l'analyse : `H1:iid`, `H1:blocs`, `D4:2024-S2`, `D4:2025-S1`, `D4:2025-S2`, `D4:2026-S1`, `D7:data:…` et `D7:boot:…`. Une étiquette n'est jamais réutilisée ; aucun flux n'est partagé entre analyses.

**Amendement D2-percentiles (verrouillé).** Sur les réplications valides triées par ordre croissant (indices à partir de 0), les bornes utilisent les indices `floor(25·(B−1)/1000)` et `floor(975·(B−1)/1000)`, sans interpolation. Pour B = 10 000 : 249 et 9749. Pour B = 1 000 : 24 et 974. Pour un autre nombre de réplications valides, la même règle s'applique à ce nombre.

## 6. D3 — Ancrage au déclenchement

**Définition normative :** le **déclenchement** est le premier état de données dans lequel les groupes range et tendance comptent chacun **au moins 60** observations éligibles (comptage seul, `T_event ≥ 2026-09-17`). La date et l'identifiant de l'import qui produit cet état sont un attribut de traçabilité, pas la définition.

**Suivi aveugle :** le compteur ne calcule et n'affiche ni temps de comblement ni comblé/non comblé, uniquement l'effectif éligible par zone ADX. Aucune analyse intermédiaire. Si le groupe range n'atteint jamais 60, il n'y a pas de verdict ; aucun repli sur un seuil plus bas sans amendement daté.

**Procédure (avant tout calcul d'issue, avec l'accord explicite de Louis) :**

1. vérifier que les bougies M15 US Tech 100 jusqu'à `2026-09-16T00:30:00Z` ont l'empreinte de référence (§ 9) ; la référence est une condition d'intégrité historique, pas une limite de la population prospective ; en cas d'écart, l'expliquer avant tout calcul ;
2. calculer, à partir des bougies uniquement, la liste des observations éligibles (`T_event`, groupe ADX, horizon réel) et τ ;
3. créer un `DatasetVersion` (US Tech 100, M15, de la première bougie à la dernière bougie de l'état déclencheur, `frozen=true`) ; il couvre tout l'historique M15, car l'ADX est un lissage récursif qui dépend de tout le passé ;
4. consigner, dans son champ `note` et dans un fichier de déclenchement suivi par git **commité avant l'analyse** : SHA-256 de toutes les bougies M15 de l'état déclencheur, effectifs par groupe, hash de la liste des observations éligibles, τ, hash du commit de code, hash du journal d'import, graine maître et paramètres ;
5. seulement ensuite calculer les issues et exécuter l'analyse **une seule fois**, après avoir revérifié l'empreinte des bougies.

**Sérialisation canonique de la liste éligible :** lignes `T_event|groupe|horizon_min`, triées par `T_event`, UTF-8, `T_event` en UTC normalisé (`YYYY-MM-DDTHH:MM:SSZ`), `horizon_min` entier, séparateur de ligne LF, aucun champ facultatif ; SHA-256 du contenu LF. Sur tous les fichiers de cette chaîne, le hash probant est celui du blob Git.

**Limite assumée :** `frozen=true` protège l'enregistrement `DatasetVersion`, pas les bougies `MarketData` (garde applicative, contournable par SQL direct). L'intégrité repose sur les hash. Les `DatasetVersion` XAUUSD (`10cf7253…` non gelé, `c2a383d2…` gelé) ne sont pas concernés et ne changent pas.

## 7. D4 — Analyse de stabilité historique

Analyse séparée, étiquetée « stabilité — non probante » et jamais « validation » : elle réutilise des données qui ont servi à choisir l'hypothèse.

- **D4.1 Objet.** Mesurer si l'écart range/tendance observé sur l'historique se concentre dans une période. D4 ne teste pas H1 et ne rétablit pas l'indépendance.
- **D4.2 Population figée.** Observations éligibles au sens D1, calculées sur la série tronquée à `2026-09-16T00:30:00Z` après vérification de l'empreinte (§ 9). Aucun import ultérieur ne la modifie. Valeur attendue : 511 observations (190 range, 321 tendance), SHA-256 de la liste canonique `T_event|groupe|horizon_min` : `c0d8cc87df8125d7a813f2fb3b99658ce97632b067899dac2ab98a9925eb21db`. Les 22 événements du § 3 en sont exclus.
- **D4.3 Périodes.** Semestres civils UTC selon `T_event` (S1 = 01/01→30/06, S2 = 01/07→31/12) : 2024-S1 (partielle, dès le 22/01), 2024-S2, 2025-S1, 2025-S2, 2026-S1, 2026-S2 (partielle, jusqu'au 14/08). Figées ; aucun autre découpage, aucune fusion, aucun redécoupage sans amendement daté.
- **D4.4 Lisibilité.** Une période est lisible si chacun des deux groupes compte au moins 30 observations ; sinon seuls les effectifs sont produits, aucune statistique n'est calculée. Ce seuil est une règle de lisibilité fixée avant les résultats ; il n'est jamais un critère de sélection : aucune période n'est retirée, ajoutée ou re-seuillée après avoir vu un Δ.

| Période | Range | Tendance | Lisible |
|---|---|---|---|
| 2024-S1 | 23 | 60 | non |
| 2024-S2 | 35 | 65 | oui |
| 2025-S1 | 37 | 57 | oui |
| 2025-S2 | 45 | 61 | oui |
| 2026-S1 | 41 | 59 | oui |
| 2026-S2 | 9 | 19 | non |

- **D4.5 τ.** Un seul τ_hist = 42765 min pour toutes les périodes : plus petit horizon réel parmi la population de D4.2 (groupes range et tendance), fixé avant toute issue. Ses RMST ne sont pas comparables en absolu à ceux de H1.
- **D4.6 Sorties par période lisible :** n par groupe ; RMST(τ_hist) par groupe ; Δ = RMST(range) − RMST(tendance) ; IC 95 % bootstrap i.i.d. stratifié (D2, étiquette `D4:<période>`, B = 10 000) ; taux de comblement à τ_hist par groupe ; décomposition du Δ ; nombre d'observations comblées après τ et de jamais comblées dans l'horizon. Rien d'autre : ni log-rank, ni p-valeur, ni bootstrap par blocs, ni médiane.
- **D4.7 Interdits.** Aucune agrégation entre périodes : ni comptage de signes (« 3 périodes sur 4 »), ni moyenne des Δ, ni conclusion globale tirée de D4.
- **D4.8 Pare-feu.** Aucun résultat de D4 ne modifie H1, D1–D3, τ, les seuils ADX 20/25, la période ADX 14, l'horizon de 2000 bougies ni la règle de déclenchement, et ne suggère d'hypothèse alternative. Un Δ de signe opposé ou un IC contenant 0 n'infirme ni ne confirme H1.
- **D4.9 Exécution.** Une seule fois, **après** le commit d'enregistrement, avec le code référencé au § 11. Le résultat va dans un fichier daté séparé, avec le commit exécuté, l'empreinte de la série et le hash de la liste ; jamais dans ce fichier. Si le commit exécuté diffère du commit cité, l'exécution est interdite. Rejeu identique permis ; rejeu à paramètres modifiés interdit.

## 8. D5 — Imports du protocole

- **Périmètre :** US Tech 100, **M15 uniquement**.
- **Cadence :** premier jour ouvré de chaque mois (UTC), à date fixe, jamais déclenchée ni décalée en fonction du marché ou des résultats. Un import manqué se rattrape au suivant, sans perte.
- **Bornes obligatoires :** `start_date` = horodatage de la dernière bougie stockée (incluse), jamais antérieur ; `end_date` = ouverture de la dernière bougie **clôturée** (heure UTC arrondie au quart d'heure inférieur, moins 15 min). Aucun import avec les valeurs par défaut du code.
- **Collision (définition) :** même horodatage déjà présent avec un OHLC différent ; comparaison exacte sur open/high/low/close, **sans aucune tolérance numérique**. Un chevauchement à OHLC identique est `unchanged` : aucune écriture. Volume et spread ne déterminent pas la collision ; ils sont rapportés à titre informatif.
- **Borne de départ :** `start_date` est obligatoirement égal à l'horodatage de la dernière bougie actuellement stockée. Un `start_date` différent (antérieur ou postérieur) refuse l'import avant toute écriture, de même qu'une bougie du lot antérieure à `start_date`.
- **R1 — arrêt strict (tranché le 2026-09-21) :** une collision n'est admise que sur la dernière bougie stockée, et seulement si celle-ci est explicitement identifiée comme partielle. Toute autre collision (bougie déjà clôturée ou antérieure) est une **anomalie bloquante** : arrêt avant toute écriture, aucun écrasement, rapport de l'ancien et du nouvel OHLC (volume et spread à titre informatif) adressé à Louis, qui décide de la suite.
- **Exception de premier import :** la bougie `2026-09-16T00:45:00Z`, explicitement identifiée comme partielle (horodatage et OHLC partiel du § 9) et postérieure à la référence, peut être mise à jour lors de sa clôture. Dès qu'elle est remplacée par sa version clôturée, elle n'est plus identifiée comme partielle : toute collision ultérieure sur elle est une anomalie.
- **Contrôle de la référence :** après chaque import, la portion historique couverte par la référence (§ 9) doit rester identique (l'empreinte de la série complète, elle, change à chaque ajout).
- **Garde-fou logiciel :** `plan_import` et `guarded_import` (`import_protocol.py`) portent ces contrôles et n'écrivent qu'après un plan valide. Le endpoint `/market-data/import` de `main.py` n'est **pas modifié et n'est pas protégé** : un import du protocole passe par `guarded_import` ; son câblage éventuel au endpoint est une décision d'implémentation ultérieure.
- **Journal d'import :** chaque import produit une entrée append-only dans le journal suivi par git et fait l'objet d'un **commit Git dédié**, après les contrôles d'import et avant toute analyse utilisant les nouvelles données (1 import → 1 entrée de journal → 1 commit). Le commit ne modifie pas rétroactivement les entrées précédentes et ne contient rien d'autre que le journal de cet import et ses fichiers de traçabilité directs. Contenu : date et heure UTC, bornes demandées, insérées / mises à jour / inchangées / collisions, première et dernière bougie, SHA-256 de la série complète, résultat de la vérification de référence, plus grand intervalle entre deux bougies consécutives et liste des intervalles > 60 min (revue humaine, non bloquant). Son hash est inclus dans le registre de déclenchement (D3).
- **Responsable :** imports exécutés sur demande explicite de Louis, mois par mois, avec les bornes imposées et MT5 ouvert. Aucune autorisation permanente. Le garde-fou logiciel du endpoint d'import est une décision d'implémentation ultérieure.
- **Dépendance :** les imports du protocole commencent après le commit d'enregistrement (§ 0). Premier import prévu : 2026-10-01.

## 9. D6 — Référence historique et attestation

**Référence historique (D3) :** bougies M15 US Tech 100 jusqu'à **`2026-09-16T00:30:00Z`** — 62521 bougies clôturées — SHA-256 `fb13b6221d7ca1382854da26b430d41d150cd1084a40e181a10eaea5533a10bc`. Procédure : bougies triées par `timestamp` (ordre strictement croissant) ; pour chacune la ligne `timestamp|open|high|low|close` + LF, valeurs telles que stockées (représentation Python par défaut) ; SHA-256 de la concaténation UTF-8. L'ancienne empreinte `bc66e254…` (62 522 bougies, dernière `2026-09-16T00:45:00Z`) est **abandonnée** comme référence : elle inclut une bougie stockée partielle.

**Attestation (constat à la préparation de ce fichier, revérifiée avant le commit)**, en quatre parties distinctes :

1. **Dernière bougie de référence clôturée :** `2026-09-16T00:30:00Z` (clôturée à 00:45 UTC), série de référence de 62521 bougies, empreinte ci-dessus.
2. **Bougie postérieure / partielle présente en base :** `2026-09-16T00:45:00Z`, écrite à 00:47:17 UTC lors de l'import initial, donc avant sa clôture (01:00) ; son OHLC stocké est partiel (open 28997.4, high 29001.9, low 28991.9, close 28993.65). Elle est **hors référence**, **hors toute série d'analyse**, et sera écrasée par le premier import (collision attendue, D5). Elle est signalée ici, non masquée.
3. **Série effectivement utilisée par les analyses historiques (D4, D7) :** les bougies dont le timestamp est ≤ `2026-09-16T00:30:00Z`, rien d'autre. Série complète stockée à ce jour : 62522 bougies, dernière `2026-09-16T00:45:00Z`, SHA-256 `bc66e254a2e0c5cd63a4214c2f710a6c4598822607864c4fd16c9cf39a92b8c2` (série complète, partielle comprise ; sans usage protocolaire).
4. **Aucune bougie postérieure clôturée n'est utilisée** dans la série de référence, **aucune bougie prospective** (`T ≥ 2026-09-17T00:00:00Z`) n'est présente, et **aucune issue prospective n'a été consultée**.

Cette attestation ne démontre pas mathématiquement l'absence de données futures : elle documente l'état constaté au moment de l'enregistrement.

## 10. D7 — Étude de conception de puissance

Étude de **conception**, réalisée avant ce fichier et avant tout registre de déclenchement. Elle ne teste pas H1.

- **D7.1 Réservoir.** Les 511 observations de D4.2, réduites à (uᵢ, eᵢ) : uᵢ = min(Tᵢ, τ_hist) ; eᵢ = 1 si comblée à t ≤ τ_hist, sinon 0 ; toute observation e = 0 vaut exactement τ_hist ; aucune information au-delà de τ_hist ; le groupe n'est pas conservé. Ordre canonique : tri par `T_event` croissant ; SHA-256 des lignes UTF-8 LF `T_event|u|e` : `2242f0e31ac3fc0c1d1be1289d5db6ab1399bfdf00e492b99896f7d8bafea6e7`.
- **D7.2 Tirage.** Pour chaque simulation, tirage uniforme avec remise dans le même réservoir poolé : n_range indices puis n_tendance indices. Aucune information de groupe n'entre dans le réservoir.
- **D7.3 Transformation.** Tendance inchangée. Range : si e = 1, u' = (1 − δ)·u et e' = 1 ; si e = 0, u' = τ_hist et e' = 0. Aucune transformation de censure, aucun arrondi ; δ = 0 est l'identité.
- **D7.4 Invariants obligatoires** (la simulation s'arrête s'ils sont violés) : l'indicateur e n'est jamais modifié ; toute observation e = 0 reste exactement à τ_hist ; aucun temps > τ_hist ; aucune censure avant τ_hist ; RMST Kaplan-Meier = moyenne des temps (tolérance relative 1e-9).
- **D7.5 Effet.** Δ_vrai(δ) = −δ·C, où C est la contribution moyenne des seuls comblements du réservoir (C = 2577.6 min ; RMST poolé = 6176.2 min ; part censurée = 43 (8.4 %) sur 511). Δ_vrai est rapporté en minutes et en % du RMST poolé. **δ est le paramètre nominal, pas l'effet observé.**
- **D7.6 Portée.** Le scénario accélère uniquement les comblements observables avant τ_hist ; il ne modifie ni la proportion de comblements ni la queue. **Cette hypothèse est conservatrice sur la queue.** τ_hist est le plafond et l'unique point de censure simulé.
- **D7.7 Grille.** δ ∈ {0, 5, 10, 15, 20, 30} % ; effectifs (n_range, n_tendance) ∈ {(60, 102), (80, 136), (100, 170)} ; par cellule : 1000 simulations ; B = 1000 bootstrap i.i.d. stratifié par simulation ; IC principal selon D1/D2 ; percentiles D2 pour B = 1000 (indices 24 et 974). **δ = 0 est une ligne témoin de calibration (faux positifs), pas une hypothèse.**
- **D7.8 Flux.** D2-flux ; étiquettes `D7:data:δ={δ}:n={n_range}/{n_tendance}:sim={k}` et `D7:boot:δ={δ}:n={n_range}/{n_tendance}:sim={k}` (δ en pourcent entier, k = 0…999), toutes uniques (36 000).
- **D7.9 Aveuglement.** Le simulateur ne reçoit que des paires (u, e), ni groupe ni `T_event` (utilisé seulement en amont pour l'ordre canonique). Sorties poolées autorisées : N, part censurée, RMST poolé, C. Interdits : Δ historique poolé, taux de comblement par groupe, RMST par groupe, résultats de D4.
- **D7.10 Règle sur le seuil.** D7 ne peut jamais abaisser le seuil sous 60/60. Un relèvement à 80 ou 100 est une **décision explicite et documentée**, jamais une conséquence automatique de la puissance. Coût en délai : 80 ≈ +3,3 mois ; 100 ≈ +6,5 mois.
- **D7.11 Statut de la puissance simulée.** Propriété conditionnelle du scénario de conception ; **ni une estimation de la puissance réelle de H1, ni une probabilité de détection**. Toute formule du type « H1 a X % de chances d'être détectée » est interdite.
- **D7.12 Limites.** Indépendance supposée (tirage i.i.d.) ; dépendance intra-semaine non modélisée (elle réduirait la puissance réelle) ; mécanisme conservateur sur la queue ; τ_hist est une hypothèse de conception ; différence avec l'analyse réelle : B = 1000 par simulation (10 000 dans l'analyse réelle), sensibilité par blocs et log-rank non simulés.

**Résultat de l'exécution** (fichier `D7_RESULT_2026-09-21.json`, SHA-256 `449f4fca76704ec00443ee71e196ee393aea350ec79bed3ec2d0516984b6e606`, exécuté le 2026-09-21T00:39:17Z, commité dans `c8ff0fbf15501b14069ba6c56d989a6b80be569e`). Lecture descriptive uniquement ; la colonne « IC exclut 0 » est le taux de faux positifs du critère pour δ = 0 (contrôle de calibration) et la puissance conditionnelle du scénario de conception pour δ > 0.

| n range / tendance | δ nominal | Δ_vrai (min) | Δ_vrai (% RMST poolé) | IC exclut 0 | bon signe | demi-largeur médiane IC (min) | Δ̂ médian (min) |
|---|---|---|---|---|---|---|---|
| 60 / 102 | 0 % | 0.0 | 0.00 % | 5.2 % | sans objet | 3936 | -101 |
| 60 / 102 | 5 % | -128.9 | -2.09 % | 5.2 % | 82.7 % | 3888 | -144 |
| 60 / 102 | 10 % | -257.8 | -4.17 % | 6.7 % | 77.6 % | 3923 | -384 |
| 60 / 102 | 15 % | -386.6 | -6.26 % | 6.1 % | 77.0 % | 3916 | -387 |
| 60 / 102 | 20 % | -515.5 | -8.35 % | 8.5 % | 78.8 % | 3874 | -570 |
| 60 / 102 | 30 % | -773.3 | -12.52 % | 7.9 % | 88.6 % | 3842 | -738 |
| 80 / 136 | 0 % | 0.0 | 0.00 % | 4.3 % | sans objet | 3425 | -30 |
| 80 / 136 | 5 % | -128.9 | -2.09 % | 5.6 % | 75.0 % | 3390 | -283 |
| 80 / 136 | 10 % | -257.8 | -4.17 % | 5.7 % | 78.9 % | 3372 | -374 |
| 80 / 136 | 15 % | -386.6 | -6.26 % | 6.2 % | 79.0 % | 3381 | -262 |
| 80 / 136 | 20 % | -515.5 | -8.35 % | 6.8 % | 86.8 % | 3362 | -536 |
| 80 / 136 | 30 % | -773.3 | -12.52 % | 8.5 % | 94.1 % | 3332 | -819 |
| 100 / 170 | 0 % | 0.0 | 0.00 % | 5.5 % | sans objet | 3066 | -46 |
| 100 / 170 | 5 % | -128.9 | -2.09 % | 5.7 % | 77.2 % | 3039 | -234 |
| 100 / 170 | 10 % | -257.8 | -4.17 % | 6.6 % | 72.7 % | 3048 | -257 |
| 100 / 170 | 15 % | -386.6 | -6.26 % | 6.4 % | 84.4 % | 3035 | -451 |
| 100 / 170 | 20 % | -515.5 | -8.35 % | 7.4 % | 82.4 % | 3030 | -491 |
| 100 / 170 | 30 % | -773.3 | -12.52 % | 9.4 % | 97.9 % | 2983 | -767 |

Aucun relèvement du seuil n'est décidé ici. Le seuil reste 60/60 (D3).

## 11. Code et reproductibilité

- **Commit contenant le code** (analyse H1, statistiques de survie, D4, D7, intégrité, protocole d'import, tests, contrôle par mutation) : `2f3acb226ac79fb4394f728ee294a1b8970c541a` sur la branche `scenario-engine-v5.1.1-fixes`.
- **Garde-fou D5 (R1) :** empreintes SHA-256 (LF) de `import_protocol.py` : `6412ee23219861a1fc3f8bdcc826882ac88703d6723f06152f8d98e62b368cf2` ; de `test_import_protocol.py` : `0b9a600b518920873aa56840df9513cf81d57a345c0867ad4739576f5421dfd9` ; de `mutation_check.py` : `f4a073eca94563e8d73a8f8955900511674edb20d492eb95d60368ddfb438e63`. Ces trois fichiers ont été modifiés après le commit `2f3acb226ac79fb4394f728ee294a1b8970c541a` ; le commit qui les contient est créé avant le commit d'enregistrement et se vérifie par ces empreintes. Ils n'appartiennent pas aux neuf fichiers dont l'empreinte est liée à l'exécution de D7.
- **Statut exact de l'exécution de D7 (sans réécriture de l'historique).** D7 a été exécutée le 2026-09-21T00:39:17Z avec l'arbre de travail dont le HEAD était `837f5469dade10807cf9c352b465399e74bdbf87` et dont les fichiers sources étaient modifiés et non commités (`code_files_dirty = true` dans le fichier de résultat) ; le résultat enregistre l'empreinte SHA-256 (LF) de chacun des neuf fichiers sources. Le commit `2f3acb226ac79fb4394f728ee294a1b8970c541a` **n'existait pas au moment de l'exécution** : il a été créé ensuite, et chacune des empreintes enregistrées a été vérifiée identique au contenu correspondant de ce commit. Ce commit est donc celui qui **contient** le code exécuté ; ce n'est pas un commit qui était déjà en place lors de l'exécution.
- **Commit du résultat D7 :** `c8ff0fbf15501b14069ba6c56d989a6b80be569e`.
- **Graine maître :** 20260918. **Paramètres de l'analyse principale :** B = 10 000, IC percentile 95 %, indices 249 et 9749.
- Chaque analyse est reproductible à l'identique : flux déterministes par étiquette, sérialisations canoniques LF, empreintes SHA-256.

## 12. Revue de cohérence D1 → D7

| Paire | Verdict | Remarque |
|---|---|---|
| D1 ↔ D2 | cohérent | Observation, censure à τ, RMST = moyenne des min(T, τ), τ fixé une fois ; flux et percentiles précisés par les amendements D2. |
| D1 ↔ D3 | cohérent | Population = éligibles matures, début prospectif, compteur aveugle sans issue, déclenchement ≥ 60 / ≥ 60. |
| D1 ↔ D4 | cohérent après précision | Exclusion explicite des 22 événements non matures (D4.2) ; τ_hist distinct du τ prospectif. |
| D1 ↔ D5 | cohérent | Dernière bougie clôturée = ouverture arrondie au quart d'heure inférieur − 15 min ; collision = même horodatage, OHLC différent (R1, § 8). |
| D1 ↔ D6 | cohérent après correction | Attestation en quatre parties ; la bougie partielle de 00:45 est signalée. |
| D1 ↔ D7 | cohérent | Même population, τ_hist, RMST, invariants ; censure préservée. |
| D2 ↔ D4 | cohérent | Flux `D4:<période>` distincts, mêmes règles statistiques. |
| D2 ↔ D7 | cohérent | Même définition d'IC et de percentiles ; différences (B, blocs, log-rank) documentées. |
| D3 ↔ D4 / D7 | cohérent | Ni compteur aveugle, ni registre de déclenchement, ni consommation de données prospectives. |
| D5 ↔ D6 | cohérent | Bougie 00:45 : seule bougie partielle identifiée, mise à jour admise au premier import ; imports après le commit d'enregistrement. |
| D4 ↔ D7 | cohérent | D7 peut utiliser le réservoir historique ; aucun résultat D4, aucun Δ par groupe dans D7. |

**Règle de collision D5 : tranchée le 2026-09-21 (R1, arrêt strict), voir § 8** ; le point ouvert signalé pendant la préparation est clos. **L'ordre « enregistrement puis implémentation » évoqué pendant la revue de D5 est remplacé par « implémentation, tests, puis enregistrement » (D4.9).**

## 13. Errata

- Horizon de 2000 bougies M15 : « ~3 semaines » dans les documents antérieurs ; mesuré ≈ 30 jours calendaires. Les commentaires de code de `gap_analysis.py` et `main.py` contiennent encore « ~3 semaines » : non modifiés, en attente d'accord.
- Délai d'accumulation : ≈ 4,9 mois pour n ≥ 30 range et ≈ 5,7 mois pour n ≥ 60 tendance ; goulot n ≥ 60 range ≈ 9,8 mois + ≈ 1 mois de maturité, soit un déclenchement attendu vers août 2027, avec plusieurs semaines d'incertitude ; il suppose des imports MT5 mensuels réguliers.
- Empreinte `bc66e254…` : abandonnée (bougie partielle). Empreinte `dc683998…` de la v0.1 : caduque.
