# Independent read of registration draft 2, and what was done

Reader: fresh Codex thread, read-only, no stake in the design. It reported inspecting no outcomes and running nothing. Verdict:
NOT READY, six findings. The reviewer checked each against source and accepted all six. Worked examples in the findings are
synthetic.

| # | Class | Finding | Verified at | Disposition |
|---|---|---|---|---|
| 1 | Non-transferring | Centering does not cancel against a pooled baseline, because hitter and pitcher categories center on different populations. The review's claim was wrong. | src/league_values/engine.py:81 | Multiplier now runs on production's centered value V = F1 - C_fam around B = min V. Predictions rank in target units. |
| 2 | Non-transferring | AgeCurve and VolumeMultiplier run before the horizon, so the study's F1 is not what `_horizon_profile` receives. The review missed this and claimed a complete reconstruction. | mlb/dynasty.py:1129, src/league_values/post_processors.py:115,157 | Hand-set now reconstructs the whole chain. Integration removes those two stages too. |
| 3 | Non-transferring | Study sums both families per asset; production keys board rows by (mlbam_id, role). | mlb/dynasty.py:327 | Rows, F1 and H3 cover the routed family only. Declared departure. |
| 4 | Invalid, contradiction | A Steamer feed published after T_2026 cannot be a T_2026 prediction. | draft | Steamer freeze is a separate transfer record with its own recorded cutoff. |
| 5 | Invalid | Percentile estimator unspecified, and handling of up to 5% undefined replicates was contradictory. | draft | Pinned linear interpolation on finite values; every replicate stays in the denominator. |
| 6 | Contradiction | The reviewer's small-slice coverage exemption changed a floor the draft claimed to retain. | charter line 112 | Exemption kept, because one missing field in a tiny slice should not void a fold. Now a declared departure, and the retention claim is corrected. |

## Added by the reviewer while fixing these
Reading finding 1 exposed a related gap: role-level intercepts could raise pooled Spearman just by shifting all of one family
against the other, a gain unrelated to age or playing time. New required condition: in the top-300 gate the gap against Hand-set
must be positive within hitters and within pitchers, in development and in H.

## Result worth keeping
Every stage in the chain is `B + factor * (value - B)` with all factors positive, so the row at the minimum stays there and all
stages share one B. Their factors multiply. The live preseason chain is therefore one multiplier:

`m = v * (c(age) + 0.72*c(age+1)*rho + 0.48*c(age+2)*rho) / 2.20`

The age curve enters year 1 in full through AgeCurve, not just as a ratio in later years. That is stronger than the reviewer
described to the owner earlier.
