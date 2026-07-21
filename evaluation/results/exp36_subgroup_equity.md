# EXP-36 subgroup equity decomposition (§4.7)

Experiment `exp36_frozen_headline`, generated 2026-07-21T15:49:51.822723+00:00.

Marking is the project's own `_MATCH_STATUS_SQL` (`dashboard/lib/db.py`), reached through `evaluation/exp36_analysis.load_rows`. The canonical set is `dedup_canonical(scope_by_label=False)`: the latest `phase2_final` per (question, country). Abstention codes are re-derived from the stored trails by `evaluation/abstention_gold_class_by_code.classify_abstentions`. `evaluation/abstention_records.csv` is not read; it is stale and holds no EXP-36 rows. Ground truth is read only to score.

## 0. Population and denominators

- Raw `phase2_final` rows: 1151; canonical pairs: **1144** (7 superseded duplicates dropped).
- Per country: BA 143, BE 143, BG 143, FI 143, HR 143, ME 143, MK 143, SE 143.
- Committed 636, abstained 508, agent failures 0.
- Gold class counts: no 370, other 235, yes 539.

Negative-gold denominators, never mixed:

| denominator | n |
| --- | ---: |
| binary-shape gold `no` (`answer_shape = 'binary'`) | 368 |
| all-shapes gold `no` (adds two `count_band` golds) | 370 |
| binary-shape gold `yes` | 539 |
| all pairs | 1144 |

## 1. Reconstructed yes-share against gold

Denominator: binary-shape golds only. Committed answers that are neither `yes` nor `no` cannot be read as either, so they are dropped from numerator and denominator alike under all three policies and counted in the `off-shape` column; the gold share is recomputed on the same reduced base so the signed error is like-for-like.

Policy (c) fills abstentions with the value being scored against. It is an oracle bound on what perfect abstention-handling could recover, not a deployable procedure.

**Table 1.1 — per-country yes-share. Denominators: gold and policies (b), (c) over effective binary-gold pairs (n col); policy (a) over committed binary-gold pairs (n committed col).**

| country | stratum | n binary gold | off-shape | n eff | n committed | gold yes-share | (a) recon | (a) err | (b) recon | (b) err | (c) recon | (c) err |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BA | A | 92 | 1 | 91 | 37 | 0.143 | 0.351 | 0.208 | 0.143 | 0.000 | 0.220 | 0.077 |
| BE | B | 115 | 0 | 115 | 70 | 0.791 | 0.929 | 0.137 | 0.565 | -0.226 | 0.826 | 0.035 |
| BG | A | 117 | 0 | 117 | 55 | 0.564 | 0.709 | 0.145 | 0.333 | -0.231 | 0.615 | 0.051 |
| FI | B | 120 | 0 | 120 | 92 | 0.758 | 0.924 | 0.166 | 0.708 | -0.050 | 0.842 | 0.083 |
| HR | B | 113 | 0 | 113 | 57 | 0.761 | 0.807 | 0.046 | 0.407 | -0.354 | 0.770 | 0.009 |
| ME | A | 113 | 1 | 112 | 58 | 0.473 | 0.534 | 0.061 | 0.277 | -0.196 | 0.509 | 0.036 |
| MK | A | 116 | 4 | 112 | 61 | 0.375 | 0.557 | 0.182 | 0.304 | -0.071 | 0.509 | 0.134 |
| SE | B | 121 | 0 | 121 | 87 | 0.777 | 0.839 | 0.062 | 0.603 | -0.174 | 0.802 | 0.025 |

## 2. Decision mix and within-decision commit accuracy

Share denominator is all pairs in the group (143 per country, 572 per stratum, 1,144 pooled). Commit-accuracy denominator is scoreable committed pairs inside that decision, shown as a fraction in each cell.

**Table 2.1 — decision mix by country. Share denominator: 143 pairs per country.**

| country | stratum | confirm n (share) | complement n (share) | change n (share) |
| --- | --- | ---: | ---: | ---: |
| BA | A | 140 (0.979) | 2 (0.014) | 1 (0.007) |
| BE | B | 112 (0.783) | 24 (0.168) | 7 (0.049) |
| BG | A | 126 (0.881) | 14 (0.098) | 3 (0.021) |
| FI | B | 128 (0.895) | 11 (0.077) | 4 (0.028) |
| HR | B | 84 (0.587) | 44 (0.308) | 15 (0.105) |
| ME | A | 49 (0.343) | 24 (0.168) | 70 (0.490) |
| MK | A | 0 (0.000) | 0 (0.000) | 143 (1.000) |
| SE | B | 77 (0.538) | 54 (0.378) | 12 (0.084) |

**Table 2.2 — commit accuracy within decision within stratum. Denominator: scoreable committed pairs in the cell (shown as matches/n).**

| group | decision | n pairs | share | commit acc [Wilson 95%] | matches/n | abstention rate [Wilson 95%] |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| stratum A | confirm | 315 | 0.551 | 0.661 [0.575, 0.738] | 84/127 | 0.581 [0.526, 0.634] |
| stratum A | complement | 40 | 0.070 | 0.556 [0.373, 0.724] | 15/27 | 0.325 [0.201, 0.480] |
| stratum A | change | 217 | 0.379 | 0.568 [0.475, 0.656] | 63/111 | 0.475 [0.409, 0.541] |
| stratum B | confirm | 401 | 0.701 | 0.762 [0.705, 0.811] | 189/248 | 0.374 [0.328, 0.422] |
| stratum B | complement | 133 | 0.233 | 0.918 [0.840, 0.960] | 78/85 | 0.353 [0.277, 0.438] |
| stratum B | change | 38 | 0.066 | 0.320 [0.172, 0.516] | 8/25 | 0.316 [0.191, 0.475] |
| pooled | confirm | 716 | 0.626 | 0.728 [0.681, 0.771] | 273/375 | 0.465 [0.429, 0.502] |
| pooled | complement | 173 | 0.151 | 0.830 [0.750, 0.889] | 93/112 | 0.347 [0.280, 0.420] |
| pooled | change | 255 | 0.223 | 0.522 [0.439, 0.604] | 71/136 | 0.451 [0.391, 0.512] |

**Table 2.3 — commit accuracy within decision within country. Denominator: scoreable committed pairs in the cell.**

| country | confirm acc (n) | complement acc (n) | change acc (n) |
| --- | ---: | ---: | ---: |
| BA | 0.620 (31/50) | 0.500 (1/2) | 0.000 (0/1) |
| BE | 0.831 (49/59) | 0.933 (14/15) | 0.250 (1/4) |
| BG | 0.739 (34/46) | 0.700 (7/10) | 0.500 (1/2) |
| FI | 0.821 (78/95) | 1.000 (6/6) | 0.000 (0/4) |
| HR | 0.561 (23/41) | 0.920 (23/25) | 0.444 (4/9) |
| ME | 0.613 (19/31) | 0.467 (7/15) | 0.667 (24/36) |
| MK | - (0/0) | - (0/0) | 0.528 (38/72) |
| SE | 0.736 (39/53) | 0.897 (35/39) | 0.375 (3/8) |

## 3. TPR, TNR, balanced accuracy and Youden's J on committed binary pairs

Denominator: **committed** binary-gold pairs only. An abstention leaves the denominator, so these are conditional-on-answering rates and are not comparable with the headline per-class recall in `exp36_analysis.binary_headline`, which charges abstentions against recall. Correctness is the project's `is_match`, so a committed off-shape answer counts as a miss for its class.

Intervals: Wilson on TPR and TNR; square-and-add (Newcombe) on their sum for balanced accuracy and Youden's J, valid because the two class denominators are disjoint.

**Table 3.1 — per-class recall on committed binary pairs. TPR denominator: committed yes-gold pairs. TNR denominator: committed no-gold (binary-shape) pairs.**

| group | n committed binary | TPR [95%] | TPR n | TNR [95%] | TNR n | balanced acc [95%] | Youden J [95%] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pooled | 523 | 0.870 [0.830, 0.902] | 295/339 | 0.489 [0.418, 0.561] | 90/184 | 0.680 [0.639, 0.719] | 0.359 [0.278, 0.438] |
| stratum A | 217 | 0.705 [0.602, 0.790] | 62/88 | 0.550 [0.464, 0.634] | 71/129 | 0.627 [0.561, 0.687] | 0.255 [0.121, 0.374] |
| stratum B | 306 | 0.928 [0.890, 0.954] | 233/251 | 0.345 [0.234, 0.477] | 19/55 | 0.637 [0.578, 0.704] | 0.274 [0.155, 0.408] |
| BA | 38 | 0.429 [0.158, 0.750] | 3/7 | 0.677 [0.501, 0.814] | 21/31 | 0.553 [0.392, 0.727] | 0.106 [-0.217, 0.455] |
| BE | 70 | 0.967 [0.888, 0.991] | 59/61 | 0.333 [0.121, 0.646] | 3/9 | 0.650 [0.537, 0.807] | 0.301 [0.074, 0.614] |
| BG | 55 | 0.879 [0.727, 0.952] | 29/33 | 0.545 [0.347, 0.731] | 12/22 | 0.712 [0.587, 0.812] | 0.424 [0.174, 0.623] |
| FI | 92 | 0.947 [0.871, 0.979] | 71/75 | 0.176 [0.062, 0.410] | 3/17 | 0.562 [0.493, 0.680] | 0.123 [-0.014, 0.359] |
| HR | 57 | 0.889 [0.765, 0.952] | 40/45 | 0.500 [0.254, 0.746] | 6/12 | 0.694 [0.557, 0.821] | 0.389 [0.113, 0.643] |
| ME | 59 | 0.643 [0.458, 0.793] | 18/28 | 0.581 [0.408, 0.736] | 18/31 | 0.612 [0.485, 0.720] | 0.224 [-0.029, 0.439] |
| MK | 65 | 0.600 [0.387, 0.781] | 12/20 | 0.444 [0.309, 0.588] | 20/45 | 0.522 [0.396, 0.638] | 0.044 [-0.208, 0.276] |
| SE | 87 | 0.900 [0.808, 0.951] | 63/70 | 0.412 [0.216, 0.640] | 7/17 | 0.656 [0.548, 0.773] | 0.312 [0.095, 0.546] |

## 4. Negative-gold false-positive rate

A false positive is a committed answer that does not match a `no` gold. Two denominators for the shape of the gold, and two for the conditioning, all reported separately and never mixed.

**Table 4.1 — FP rate, binary-shape gold `no` (pooled n = 368). Left rate divides by all no-golds; right rate divides by committed no-golds only.**

| group | n no-golds | n committed | n FP | FP / all no-golds [95%] | FP / committed no-golds [95%] |
| --- | ---: | ---: | ---: | ---: | ---: |
| pooled | 368 | 184 | 94 | 0.255 [0.214, 0.302] | 0.511 [0.439, 0.582] |
| stratum A | 261 | 129 | 58 | 0.222 [0.176, 0.276] | 0.450 [0.366, 0.536] |
| stratum B | 107 | 55 | 36 | 0.336 [0.254, 0.430] | 0.655 [0.523, 0.766] |
| BA | 78 | 31 | 10 | 0.128 [0.071, 0.220] | 0.323 [0.186, 0.499] |
| BE | 24 | 9 | 6 | 0.250 [0.120, 0.449] | 0.667 [0.354, 0.879] |
| BG | 51 | 22 | 10 | 0.196 [0.110, 0.325] | 0.455 [0.269, 0.653] |
| FI | 29 | 17 | 14 | 0.483 [0.314, 0.656] | 0.824 [0.590, 0.938] |
| HR | 27 | 12 | 6 | 0.222 [0.106, 0.408] | 0.500 [0.254, 0.746] |
| ME | 59 | 31 | 13 | 0.220 [0.134, 0.341] | 0.419 [0.264, 0.592] |
| MK | 73 | 45 | 25 | 0.342 [0.244, 0.457] | 0.556 [0.412, 0.691] |
| SE | 27 | 17 | 10 | 0.370 [0.215, 0.558] | 0.588 [0.360, 0.784] |

**Table 4.2 — FP rate, all-shapes gold `no` (pooled n = 370). Left rate divides by all no-golds; right rate divides by committed no-golds only.**

| group | n no-golds | n committed | n FP | FP / all no-golds [95%] | FP / committed no-golds [95%] |
| --- | ---: | ---: | ---: | ---: | ---: |
| pooled | 370 | 185 | 95 | 0.257 [0.215, 0.304] | 0.514 [0.442, 0.585] |
| stratum A | 262 | 129 | 58 | 0.221 [0.175, 0.275] | 0.450 [0.366, 0.536] |
| stratum B | 108 | 56 | 37 | 0.343 [0.260, 0.436] | 0.661 [0.530, 0.771] |
| BA | 79 | 31 | 10 | 0.127 [0.070, 0.218] | 0.323 [0.186, 0.499] |
| BE | 24 | 9 | 6 | 0.250 [0.120, 0.449] | 0.667 [0.354, 0.879] |
| BG | 51 | 22 | 10 | 0.196 [0.110, 0.325] | 0.455 [0.269, 0.653] |
| FI | 29 | 17 | 14 | 0.483 [0.314, 0.656] | 0.824 [0.590, 0.938] |
| HR | 27 | 12 | 6 | 0.222 [0.106, 0.408] | 0.500 [0.254, 0.746] |
| ME | 59 | 31 | 13 | 0.220 [0.134, 0.341] | 0.419 [0.264, 0.592] |
| MK | 73 | 45 | 25 | 0.342 [0.244, 0.457] | 0.556 [0.412, 0.691] |
| SE | 28 | 18 | 11 | 0.393 [0.236, 0.576] | 0.611 [0.386, 0.797] |

## 5. Stratum x gold class x outcome

committed = D37 commit (accepted terminal status, non-abstention final answer); abstained = every other pair. EXP-36 logged zero agent_failure rows, so abstained is entirely honest abstention.

**Table 5.1 — cross-tab. Denominator for the abstention rate is the cell n.**

| gold class | stratum | n | committed | abstained | abstention rate [95%] | commit acc [95%] (n) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| yes | A | 177 | 88 | 89 | 0.503 [0.430, 0.576] | 0.705 [0.602, 0.790] (62/88) |
| yes | B | 362 | 251 | 111 | 0.307 [0.261, 0.356] | 0.928 [0.890, 0.954] (233/251) |
| no | A | 262 | 129 | 133 | 0.508 [0.447, 0.568] | 0.550 [0.464, 0.634] (71/129) |
| no | B | 108 | 56 | 52 | 0.481 [0.390, 0.575] | 0.339 [0.229, 0.470] (19/56) |
| other | A | 133 | 56 | 77 | 0.579 [0.494, 0.659] | 0.604 [0.463, 0.730] (29/48) |
| other | B | 102 | 56 | 46 | 0.451 [0.358, 0.548] | 0.451 [0.323, 0.586] (23/51) |
| absent | A | 0 | 0 | 0 | - | - (0/0) |
| absent | B | 0 | 0 | 0 | - | - (0/0) |

**Table 5.2 — does the abstention gap survive conditioning on gold class? Marginal denominator: 572 pairs per stratum.**

| test | A | B | delta (A-B) | 95% CI on delta | p |
| --- | ---: | ---: | ---: | ---: | ---: |
| marginal (unconditioned) | 0.523 [0.482, 0.563] | 0.365 [0.327, 0.406] | 0.157 | [0.100, 0.213] | 0.000 |
| within gold = yes | 0.503 | 0.307 | 0.196 | [0.108, 0.282] | 0.000 |
| within gold = no | 0.508 | 0.481 | 0.026 | [-0.085, 0.136] | 0.647 |
| within gold = other | 0.579 | 0.451 | 0.128 | [-0.001, 0.251] | 0.052 |

Cochran-Mantel-Haenszel, stratum against outcome conditioned on gold class: chi-square = 16.890 on 1 df, p = 0.000, MH common odds ratio = 0.591, over 3 non-empty gold classes. The odds ratio is for **committing** in A relative to B, so a value below 1 means stratum A commits less often (abstains more) inside the gold classes, not only across them.

The gap is not uniform across the classes it survives: within `no` golds the two strata abstain at almost the same rate (0.508 against 0.481, p = 0.647), and the marginal gap is carried by the `yes` golds (0.503 against 0.307, p = 0.000). Conditioning does not remove the association, but it does relocate it.

## 6. Abstention codes by stratum and gold class

Codes are the priority-list first-match markers, so a code is where a pair first stopped, not a causal attribution.

**Table 6.1 — abstention counts by code and stratum. Denominator: the 508 abstentions.**

| code | A | B | total | A gold yes/no/other | B gold yes/no/other |
| --- | ---: | ---: | ---: | ---: | ---: |
| B | 16 | 0 | 16 | 3/10/3 | 0/0/0 |
| C | 4 | 8 | 12 | 0/0/4 | 2/0/6 |
| D | 10 | 14 | 24 | 1/2/7 | 12/1/1 |
| E | 101 | 107 | 208 | 39/41/21 | 58/26/23 |
| G | 143 | 56 | 199 | 44/72/27 | 29/17/10 |
| I | 13 | 17 | 30 | 1/1/11 | 7/6/4 |
| Z | 12 | 7 | 19 | 1/7/4 | 3/2/2 |

G composition check: G holds 199 abstentions, of which 162 carry a yes/no gold (73 yes, 89 no), a yes-share of **0.451** against the held-out base rate of **0.593** (all-shapes gold yes/no (n=909)).

**Table 6.2 — G by stratum within gold class. Two denominators: G per pair (cell n pairs) and G per abstention (cell n abstentions).**

| gold class | stratum | n pairs | n abstentions | n G | G/pair [95%] | G/abstention [95%] |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| yes | A | 177 | 89 | 44 | 0.249 [0.191, 0.317] | 0.494 [0.393, 0.596] |
| yes | B | 362 | 111 | 29 | 0.080 [0.056, 0.113] | 0.261 [0.189, 0.350] |
| no | A | 262 | 133 | 72 | 0.275 [0.224, 0.332] | 0.541 [0.457, 0.624] |
| no | B | 108 | 52 | 17 | 0.157 [0.101, 0.238] | 0.327 [0.215, 0.462] |
| other | A | 133 | 77 | 27 | 0.203 [0.143, 0.279] | 0.351 [0.253, 0.462] |
| other | B | 102 | 46 | 10 | 0.098 [0.054, 0.171] | 0.217 [0.123, 0.356] |

**Table 6.3 — G concentration in stratum A, marginal against conditioned.**

| denominator | A | B | delta | p (marginal) | CMH chi-square | CMH p | MH odds ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| G per pair (572 per stratum) | 0.250 | 0.098 | 0.152 | 0.000 | 33.520 | 0.000 | 2.719 |
| G per abstention | 0.478 | 0.268 | 0.210 | 0.000 | 19.373 | 0.000 | 2.443 |

## 7. Country-level permutation tests (4 against 4)

The country-level test permutes the eight country labels, so the 143 pairs inside a country move together and within-country clustering is handled by construction. The pair-level test treats the 1,144 pairs as independent, which they are not: pairs cluster within country, so its p-value is anti-conservative and is reported only as a comparator.

**Table 7.1 — exact country-level test. 70 arrangements, so the smallest achievable two-sided p is 2/70 = 0.029.**

| endpoint | observed delta (A-B, mean of country rates) | arrangements at least as extreme | exact p | at floor |
| --- | ---: | ---: | ---: | --- |
| abstention | 0.157 | 8/70 | 0.114 | no |
| commit accuracy | -0.148 | 4/70 | 0.057 | no |

**Table 7.2 — per-country rates feeding the permutation. Abstention denominator: 143 pairs. Commit-accuracy denominator: scoreable committed pairs.**

| country | stratum | abstention rate | commit accuracy |
| --- | --- | ---: | ---: |
| BA | A | 0.615 | 0.604 |
| BE | B | 0.448 | 0.821 |
| BG | A | 0.573 | 0.724 |
| FI | B | 0.259 | 0.800 |
| HR | B | 0.462 | 0.667 |
| ME | A | 0.420 | 0.610 |
| MK | A | 0.483 | 0.528 |
| SE | B | 0.294 | 0.770 |

**Table 7.3 — pair-level comparator. Anti-conservative: pairs cluster within country and this test ignores that.**

| endpoint | denominator | A | B | delta | 95% CI | p (pair-level) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| abstention | all pairs (A n=572, B n=572) | 0.523 | 0.365 | 0.157 | [0.100, 0.213] | 0.000 |
| commit accuracy | scoreable committed pairs | 0.611 | 0.768 | -0.157 | [-0.229, -0.084] | 0.000 |

The two units disagree, and the disagreement is the point. At pair level both gaps clear any conventional threshold (p < 0.001); at country level neither does (p = 0.114 for abstention, 0.057 for commit accuracy). The stratum contrast rests on eight countries, and the country is the unit the stratum is defined over, so the country-level p-values are the ones that carry. Neither gap is separable from country-to-country variation at n = 8. The direction is consistent across the four-country groups; the significance is not established.

## 8. Belgium isolate

Catalogue recomputability: harvestable national catalogue for FI, HR, SE, ME; none for BG, MK, BE, BA. The catalogue split swaps BE and ME relative to the D47 stratum split; it is a competing grouping, not a nested one.

**Table 8.1 — BE against the rest of stratum B. Abstention denominator: all pairs. Commit-accuracy denominator: scoreable committed pairs. TPR/TNR denominator: committed binary-gold pairs of that class.**

| metric | BE [95%] (n) | FI+SE+HR [95%] (n) | delta | 95% CI | p |
| --- | ---: | ---: | ---: | ---: | ---: |
| abstention rate | 0.448 [0.368, 0.529] (64/143) | 0.338 [0.295, 0.384] (145/429) | 0.110 | [0.018, 0.202] | 0.018 |
| commit accuracy | 0.821 [0.721, 0.890] (64/78) | 0.754 [0.700, 0.800] (211/280) | 0.067 | [-0.043, 0.155] | 0.215 |
| TPR | 0.967 [0.888, 0.991] (59/61) | 0.916 [0.868, 0.948] (174/190) | 0.051 | [-0.034, 0.105] | 0.176 |
| TNR | 0.333 [0.121, 0.646] (3/9) | 0.348 [0.227, 0.492] (16/46) | -0.014 | [-0.272, 0.321] | 0.933 |

**Table 8.2 — the catalogue grouping as a competing split. Same denominators as Table 8.1, over 572 pairs per group.**

| metric | no catalogue (BG, MK, BE, BA) | catalogue (FI, HR, SE, ME) | delta | 95% CI | p |
| --- | ---: | ---: | ---: | ---: | ---: |
| abstention rate | 0.530 [0.489, 0.570] (303/572) | 0.358 [0.320, 0.399] (205/572) | 0.171 | [0.114, 0.227] | 0.000 |
| commit accuracy | 0.674 [0.615, 0.728] (176/261) | 0.721 [0.673, 0.765] (261/362) | -0.047 | [-0.120, 0.026] | 0.209 |
| TPR | 0.851 [0.777, 0.904] (103/121) | 0.881 [0.831, 0.917] (192/218) | -0.029 | [-0.112, 0.043] | 0.439 |
| TNR | 0.523 [0.430, 0.616] (56/107) | 0.442 [0.336, 0.553] (34/77) | 0.082 | [-0.064, 0.222] | 0.273 |

**Table 8.3 — exact country-level permutation for the catalogue split, same 70 arrangements as Table 7.1, so the two splits are directly comparable.**

| endpoint | observed delta (no catalogue - catalogue) | exact p |
| --- | ---: | ---: |
| abstention | 0.171 | 0.057 |
| commit accuracy | -0.043 | 0.571 |

## 9. What could not be computed, and where n is too small

### 9.1 Not computable from the data

- **Upper bound on commit accuracy under the D22 staleness band.** ODMI gold can be one cycle old, so some disagreements are stale gold rather than swarm error. Separating them needs a human review of each disagreement, which does not exist yet. Every commit-accuracy figure here is therefore a lower bound.
- **Absent-gold cells.** The cross-tab reserves a gold class for `absent`, but all 1,144 canonical pairs carry a gold response, so the class is empty and its stratum contrast is undefined rather than zero.
- **Causal attribution for the abstention codes.** The priority list is a first-match marker: a pair that would satisfy several predicates is recorded under the first one in the order. Code counts are therefore descriptive, and the conditioned tests speak to composition, not cause.
- **A clean separation of language resource from catalogue access.** The two candidate groupings differ by exactly one swap (BE for ME), so with eight countries no test can attribute a gap to one rather than the other. Both splits are reported side by side and the comparison is descriptive.
- **Per-country TNR for several countries at a usable precision.** Committed no-gold pairs per country run to a few dozen at most, so the country-level TNR intervals are too wide to rank countries against each other.
- **Any within-country stratification below the country level.** With 143 pairs per country, splitting further by dimension and gold class at once produces cells in single figures, which is why the decomposition stops at stratum x gold class.
- **A country-level p below 0.029 for any endpoint.** Eight countries admit 70 four-against-four arrangements, so the smallest two-sided p the design can produce is 2/70 = 0.029, and that only when the observed split is the single most extreme of the 70. A null result at country level is therefore a statement about the design's resolution as much as about the swarm; it does not license the reverse claim that the strata behave alike.

### 9.2 Cells with n < 20

46 rate cells fall below n = 20. They are emitted for completeness and cannot carry a claim; the Wilson intervals on them span most of the unit interval.

| cell | successes | n | rate |
| --- | ---: | ---: | ---: |
| `s2_decision_mix.by_country.MK.by_decision.complement.abstention_rate` | 0 | 0 | - |
| `s2_decision_mix.by_country.MK.by_decision.complement.commit_accuracy` | 0 | 0 | - |
| `s2_decision_mix.by_country.MK.by_decision.confirm.abstention_rate` | 0 | 0 | - |
| `s2_decision_mix.by_country.MK.by_decision.confirm.commit_accuracy` | 0 | 0 | - |
| `s5_crosstab_gold_class.cells.absent.A.abstention_rate` | 0 | 0 | - |
| `s5_crosstab_gold_class.cells.absent.A.commit_accuracy` | 0 | 0 | - |
| `s5_crosstab_gold_class.cells.absent.B.abstention_rate` | 0 | 0 | - |
| `s5_crosstab_gold_class.cells.absent.B.commit_accuracy` | 0 | 0 | - |
| `s6_abstention_codes.G_by_stratum_and_gold_class.absent.A.G_per_abstention` | 0 | 0 | - |
| `s6_abstention_codes.G_by_stratum_and_gold_class.absent.A.G_per_pair` | 0 | 0 | - |
| `s6_abstention_codes.G_by_stratum_and_gold_class.absent.B.G_per_abstention` | 0 | 0 | - |
| `s6_abstention_codes.G_by_stratum_and_gold_class.absent.B.G_per_pair` | 0 | 0 | - |
| `s2_decision_mix.by_country.BA.by_decision.change.abstention_rate` | 0 | 1 | 0.000 |
| `s2_decision_mix.by_country.BA.by_decision.change.commit_accuracy` | 0 | 1 | 0.000 |
| `s2_decision_mix.by_country.BA.by_decision.complement.abstention_rate` | 0 | 2 | 0.000 |
| `s2_decision_mix.by_country.BA.by_decision.complement.commit_accuracy` | 1 | 2 | 0.500 |
| `s2_decision_mix.by_country.BG.by_decision.change.commit_accuracy` | 1 | 2 | 0.500 |
| `s2_decision_mix.by_country.BG.by_decision.change.abstention_rate` | 0 | 3 | 0.000 |
| `s2_decision_mix.by_country.BE.by_decision.change.commit_accuracy` | 1 | 4 | 0.250 |
| `s2_decision_mix.by_country.FI.by_decision.change.abstention_rate` | 0 | 4 | 0.000 |
| `s2_decision_mix.by_country.FI.by_decision.change.commit_accuracy` | 0 | 4 | 0.000 |
| `s2_decision_mix.by_country.FI.by_decision.complement.commit_accuracy` | 6 | 6 | 1.000 |
| `s2_decision_mix.by_country.BE.by_decision.change.abstention_rate` | 3 | 7 | 0.429 |
| `s3_class_recall_committed.by_country.BA.tpr` | 3 | 7 | 0.429 |
| `s2_decision_mix.by_country.SE.by_decision.change.commit_accuracy` | 3 | 8 | 0.375 |
| `s2_decision_mix.by_country.HR.by_decision.change.commit_accuracy` | 4 | 9 | 0.444 |
| `s3_class_recall_committed.by_country.BE.tnr` | 3 | 9 | 0.333 |
| `s4_negative_gold_fp.by_country.BE.all_shapes.fp_over_committed_no_golds` | 6 | 9 | 0.667 |
| `s4_negative_gold_fp.by_country.BE.binary_shape.fp_over_committed_no_golds` | 6 | 9 | 0.667 |
| `s8_belgium_isolate.be.tnr` | 3 | 9 | 0.333 |
| `s2_decision_mix.by_country.BG.by_decision.complement.commit_accuracy` | 7 | 10 | 0.700 |
| `s2_decision_mix.by_country.FI.by_decision.complement.abstention_rate` | 5 | 11 | 0.455 |
| `s2_decision_mix.by_country.SE.by_decision.change.abstention_rate` | 3 | 12 | 0.250 |
| `s3_class_recall_committed.by_country.HR.tnr` | 6 | 12 | 0.500 |
| `s4_negative_gold_fp.by_country.HR.all_shapes.fp_over_committed_no_golds` | 6 | 12 | 0.500 |
| `s4_negative_gold_fp.by_country.HR.binary_shape.fp_over_committed_no_golds` | 6 | 12 | 0.500 |
| `s2_decision_mix.by_country.BG.by_decision.complement.abstention_rate` | 4 | 14 | 0.286 |
| `s2_decision_mix.by_country.BE.by_decision.complement.commit_accuracy` | 14 | 15 | 0.933 |
| `s2_decision_mix.by_country.HR.by_decision.change.abstention_rate` | 6 | 15 | 0.400 |
| `s2_decision_mix.by_country.ME.by_decision.complement.commit_accuracy` | 7 | 15 | 0.467 |
| `s3_class_recall_committed.by_country.FI.tnr` | 3 | 17 | 0.176 |
| `s3_class_recall_committed.by_country.SE.tnr` | 7 | 17 | 0.412 |
| `s4_negative_gold_fp.by_country.FI.all_shapes.fp_over_committed_no_golds` | 14 | 17 | 0.824 |
| `s4_negative_gold_fp.by_country.FI.binary_shape.fp_over_committed_no_golds` | 14 | 17 | 0.824 |
| `s4_negative_gold_fp.by_country.SE.binary_shape.fp_over_committed_no_golds` | 10 | 17 | 0.588 |
| `s4_negative_gold_fp.by_country.SE.all_shapes.fp_over_committed_no_golds` | 11 | 18 | 0.611 |
