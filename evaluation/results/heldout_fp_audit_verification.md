# Held-out FP audit: manual verification of the gold-challenged cases

The automated two-pass audit (`evaluation/heldout_fp_audit.py`) flagged seven
held-out false positives as gold-challenged: six that pass 1 called
`defensible_or_stale_gold` and one that pass 2 called `gold_wrong` (the swarm
right, ODMI wrong). These are the only cases in the run of 83 where a judge
argued the gold "no" might be mistaken, so each was checked by hand against the
stored evidence the swarm actually cited. The set overlaps to six distinct
pairs (SE I27 is both the single `gold_wrong` and a `defensible_or_stale_gold`).

## Result

None of the six survives as a clean case of the swarm being right and the gold
wrong. Each traces to thin, tangential, planned, or generic evidence, the same
pattern the Netherlands audit found. The evidence-checked headline is therefore
**0/83**, matching the NL result of 0/22.

| Pair | Question asks for | Evidence actually cited | Verdict on inspection |
|---|---|---|---|
| BA P27 | activities assisting data holders to publish open data | an EU-funded CSI Piemonte project page: "technical training for IDDEEA experts", metadata standards | external project, not sustained national activity; gold "no" defensible |
| ME I9 | activities to understand reusers' data needs | an OGP commitment stating the *problem* (weak portal visibility) and a planned Open Data Days | planned/aspirational, not evidence the activity ran; gold defensible |
| ME P7 | a national strategy/policy document fostering discoverability on data.europa.eu | a portal implementation blurb from data.gov.me | wrong artefact type (implementation, not strategy); over-read; gold stands |
| ME PT12 | a notification mechanism (e.g. ATOM feed) for portal updates | a BIRN news item: revamped portal, ~400 datasets | evidence does not establish the feed; the advocate asserted an ATOM feed absent from the quote; gold defensible |
| MK P27 | activities assisting data holders to publish open data | an OGP action plan (Dec 2021 to Apr 2022) to support 30 local governments | planned action, not implemented; over-read; gold stands |
| SE I27 | quantified economic-impact data on open data reuse, country-specific | one snippet: a 2020 entryscape.com company blog pointing at the generic pan-EU report "The Economic Impact of Open Data" | not Sweden-specific impact data; see fabrication note below; gold defensible |

## Method caveat: the adversarial advocate can fabricate evidence

The single `gold_wrong` (SE I27) does not hold. Pass 2 was told to build the
strongest case for the swarm, and its best case cited a Lantmäteriet estimate of
10 to 21 billion SEK per year and a Stockholm School of Economics study funded by
Vinnova. Neither figure appears in the frozen snippet or the swarm's evidence
quote, which is a 2020 blog post about a Europe-wide report. The advocate
supplied those specifics from its own parametric knowledge. Whether or not such
Swedish studies exist, they are not what the swarm cited, so they cannot vindicate
this answer. Under the evidence the swarm actually retrieved, SE I27 is an
over-read of a generic EU report, not a country-specific impact finding.

Consequence for the method: the raw `gold_wrong` count overstates swarm
vindication, because an advocate prompted for the best case will introduce facts
not present in the shown snippets. Every gold-challenged case (n=6) was therefore
verified by hand here; none held. Future runs should either constrain the
advocate to quote only from the supplied snippets, or treat `gold_wrong` and
`defensible_or_stale_gold` strictly as flags for human review rather than as
conclusions.

## Bottom line

- 0/83 held-out false positives are a clean case of the swarm being right and
  ODMI wrong (evidence-checked), consistent with NL 0/22.
- The apparent false positives are swarm over-reads, definitional gaps, or
  genuine errors on thin evidence, not artefacts of a stale or self-reported gold.
- The D22 staleness band on the EXP-36 held-out headline is therefore negligible:
  the commit-accuracy figure is not materially depressed by out-of-date golds.
