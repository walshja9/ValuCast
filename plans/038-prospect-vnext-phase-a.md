# Plan 038 — Prospect vNext Phase A

**Status: REGISTERED - UNSPENT - NO EXECUTION AUTHORIZED**

Registered 2026-08-21 as one research-only, non-serving held-out development
screen. This document records a frozen protocol, not a metric result, model
promotion, board change, valuation change, publication claim, or authorization
to open outcome-bearing inputs.

The approved design is bound at
`1737468b16717ee6f7d24ea08b8444fdde3442f2`; the final reviewed implementation
is bound at `e1229bacc1c64d651609a5e621de0ec528a79a78`. Execution requires a later,
explicit owner approval naming the exact merged execution SHA and satisfying
every registered pre-marker check.

Plan 038 supersedes only the retired, unspent model tracks recorded append-only
in Plans 031 and 034. Plan 034's separate buy-momentum and cross-universe tracks
remain active and unchanged. The old local-only v2.3 design commit
`027a6efa7d432a6a466d2ca4d37c28e7abd9da1c` and plan commit
`1201b799eb4c73f69d5191167cb7a0494fadceca` are
`superseded_unspent / retired_never_execute`; their runner is never authorized.

The fenced object below is the exact machine-registration mirror. Its
`registration_status_at_seal` is immutable historical metadata. After any
authorized execution, current status must come from the sealed terminal receipt
and an append-only transition below this registered block.

<!-- prospect-vnext-phase-a-registration:start -->
```json
{
  "schema": "valucast_prospect_rank_v2_3_registration_v1",
  "registration_id": "plan_038_prospect_vnext_phase_a",
  "registration_status_at_seal": "registered_unspent",
  "candidate": {
    "approved_design_commit": "1737468b16717ee6f7d24ea08b8444fdde3442f2",
    "implementation_commit": "e1229bacc1c64d651609a5e621de0ec528a79a78",
    "family": "shared_threshold_role_slope_joint_ordered_logit",
    "parameter_order": [
      "tau_bust_role",
      "log_gap",
      "beta_hitter",
      "beta_pitcher",
      "gamma"
    ],
    "threshold_formula": {
      "tau_bust_role": "params[0]",
      "tau_role_star": "tau_bust_role + exp(log_gap)"
    },
    "standardization": {
      "fit_scope": "training_only_by_role",
      "centers": "finite",
      "scales": "finite_and_strictly_positive"
    },
    "linear_predictor": "beta_hitter*z*is_hitter + beta_pitcher*z*is_pitcher + gamma*is_pitcher",
    "fit_helper": {
      "module": "prospects.ordinal_calibration_power",
      "functions": [
        "_fit_ordered_logit",
        "_ordered_probabilities",
        "_expected_tier"
      ],
      "reuse_existing_objective_bounds_optimizer_tolerance_initialization_and_max_iterations": true
    },
    "fit_requirements": {
      "beta_hitter": "finite_and_strictly_positive",
      "beta_pitcher": "finite_and_strictly_positive",
      "gamma": "finite",
      "thresholds": "finite",
      "role_centers": "finite",
      "role_scales": "finite_and_strictly_positive"
    },
    "ladders": {
      "hitter": "frozen_v1_hitter",
      "pitcher": "frozen_v0_9_pitcher"
    },
    "board_order": [
      "unrounded_expected_tier_desc",
      "source_ladder_position_asc",
      "numeric_mlbam_id_asc"
    ],
    "fatal_checks": [
      "identity_mismatch",
      "within_role_inversion"
    ],
    "targets": {
      "values": {
        "bust": 0,
        "role": 0.5,
        "star": 1
      },
      "window": "cohort_year_plus_1_through_plus_4",
      "hitter_role": {
        "pa_at_least_in_one_season": 300
      },
      "hitter_star": {
        "pa_at_least_in_one_season": 450,
        "ops_at_least_same_season": 0.8
      },
      "pitcher_role": {
        "ip_at_least_in_one_season": 50
      },
      "pitcher_star": {
        "ip_at_least_in_one_season": 120,
        "era_at_most_same_season": 3.75
      }
    },
    "pooled_fit": {
      "scope": "candidate_only_2018_2019_2021",
      "timing": "after_all_fold_and_bootstrap_gates_pass",
      "rescue": false,
      "failure": "terminal_nonqualified",
      "serving_status": "non_serving"
    }
  },
  "predecessors": {
    "scientific_dependencies": {
      "v0_9_model": "immutable_input",
      "v2_1_receipt": "immutable_input",
      "v2_2_receipt": "immutable_input"
    },
    "plan_031": {
      "plan_path": "plans/031-pitcher-strike-pct-gate.md",
      "track": "model_track",
      "transition": "superseded_by_plan_038",
      "held_seed": 31013,
      "seed_status": "retired_unspent_never_execute",
      "originating_transition_commit": "55123a4786bf91b756f64b055f7972d5500884eb",
      "pre_transition_blob": "efd7c00558581915a32a76c171ddfe74357731a3",
      "post_transition_blob": "49cea65a385e7db2c48b96673f2118f7004c5b4b",
      "append_only_prefix_bytes": 18006,
      "history_evidence": {
        "scope_tip": "e1229bacc1c64d651609a5e621de0ec528a79a78",
        "standalone_pattern": "(^|[^0-9])31013([^0-9]|$)",
        "inventory_schema": "git_blob_path_offset_v1",
        "object_count": 25964,
        "sorted_object_ids_sha256": "338ecf8463398b9702b9963475a99cb18d160f6a730d64d8a66fcc621484a35c",
        "inventory_entry_count": 94,
        "inventory_sha256": "450ddd925a4b37f85dac7e1d939d63c710d4471a69c4ecf2004031561e0c42ae",
        "classification_schema": "git_blob_path_offset_line_sha256_classification_v1",
        "classifications": [
          {
            "object_id": "04811ecb46b6a44838d29429f5b18598ccb59d0b",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "055b2f74e5f55fb7cc47b5b7d10436dd8c884607",
            "path": "tests/test_prospect_challenger_eval.py",
            "byte_offset": 6029,
            "line_sha256": "4c64ea71bf53b1dd820a21b294c921d443167bb5912e68a3adcac60dbc7cb26b",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "0db5b5e08a7abdeacf17975484a0c08c12b617d2",
            "path": "tests/test_mlb_pitcher_skill_registration.py",
            "byte_offset": 193,
            "line_sha256": "bbeb5aa19613503d4b43b0d9109f4c8bca6b3d2d56e093b2613f3793499298d5",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "0e13e025be080c266db1850375b5a86eeb78a12d",
            "path": "plans/033-prospect-normalized-production-gate.md",
            "byte_offset": 7468,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "10a8afa9377a2e7392e42439fd86a260992a9eff",
            "path": "prospects/challenger_eval.py",
            "byte_offset": 1013,
            "line_sha256": "e82be979672a575ea35b9955488f7deff5c2110cb17a76d7f940b28b20935f66",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "17fec82ade1e72dee5250ae96fae41200d209059",
            "path": "tests/fixtures/prospect_v23_registration_static_preimage.json",
            "byte_offset": 2889,
            "line_sha256": "9daea53fd7d0120978309ce292bd0d9e34ed6ce7b739a730baefe492cb40d155",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "1e7126e4921fedabfba1f343c892ecc8e2f43ca0",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 7056,
            "line_sha256": "e3033c0989c9c1c1a26d302d226523630ab6475d8de0828a7f298be765675fc4",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "1e7126e4921fedabfba1f343c892ecc8e2f43ca0",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 8431,
            "line_sha256": "1c5ec6eabc6b83a5d7c82536e977727d26364bf21cab62c41ec75e695aedcd0e",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "25e201cf4cfd0bcdda0d7a50343a2c358f348189",
            "path": "tests/test_prospect_challenger_eval.py",
            "byte_offset": 5937,
            "line_sha256": "4c64ea71bf53b1dd820a21b294c921d443167bb5912e68a3adcac60dbc7cb26b",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "29f97833e51725e9db9ee6ec5693fad4c15ce616",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "2e8185e80ca072c5d81e8d13d9bfbdf5717f7121",
            "path": "tests/test_prospect_challenger_eval.py",
            "byte_offset": 4996,
            "line_sha256": "4c64ea71bf53b1dd820a21b294c921d443167bb5912e68a3adcac60dbc7cb26b",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "308994becfd343f7e50410401623c17eb1081505",
            "path": "prospects/challenger_eval.py",
            "byte_offset": 640,
            "line_sha256": "e82be979672a575ea35b9955488f7deff5c2110cb17a76d7f940b28b20935f66",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "32b28c8961be722310d0b75d5c0493ed277186a7",
            "path": "docs/program-2026-08-14-pitcher-pass.md",
            "byte_offset": 768,
            "line_sha256": "1c35e18daa05e36f13aa9f764675ded703ebad110d7b93c50a55e18a26e5ab92",
            "classification": "governance_text"
          },
          {
            "object_id": "32b6dccd801fb70a2dd6cc3594ffd401b8a1b726",
            "path": "plans/README.md",
            "byte_offset": 29976,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "3473d801d5e3791f13e84f1ecb8fe727e7e22fbc",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "36d8dcbf83de51dd9a1702720846b764cdbfbbb9",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "3cbde1971acb4cba45d2ddb30795ae597d0c251f",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "414daa0e3de62c00f6cd28fb3ccea614f5461003",
            "path": "plans/README.md",
            "byte_offset": 30176,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "4224a80c6c8953c5e088251ddc3878f14d142344",
            "path": "plans/033-prospect-normalized-production-gate.md",
            "byte_offset": 7274,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "42fa75e0760006bd28acab2a8a5be847d7212005",
            "path": "docs/program-2026-08-14-pitcher-pass.md",
            "byte_offset": 828,
            "line_sha256": "1c35e18daa05e36f13aa9f764675ded703ebad110d7b93c50a55e18a26e5ab92",
            "classification": "governance_text"
          },
          {
            "object_id": "432f0876767095bd9969c7e32c55ceee6cd55585",
            "path": "tests/test_prospect_challenger_eval.py",
            "byte_offset": 6029,
            "line_sha256": "4c64ea71bf53b1dd820a21b294c921d443167bb5912e68a3adcac60dbc7cb26b",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "4401b9929d55bc80df2b2907aea48982032d7f50",
            "path": "plans/034-post-2026-prospect-challenger-epoch.md",
            "byte_offset": 7326,
            "line_sha256": "bbeb5aa19613503d4b43b0d9109f4c8bca6b3d2d56e093b2613f3793499298d5",
            "classification": "governance_text"
          },
          {
            "object_id": "482c45994eb2ccfa5cb302950ecb890d90658fe9",
            "path": "data/prediction_archive/valucast_prospect_rank_v1/2026-06-26.json",
            "byte_offset": 442539,
            "line_sha256": "8485e6e51540121007122d491a33fb5d6fba84c898be478deff8f04eb0d86d82",
            "classification": "unrelated_numeric_data"
          },
          {
            "object_id": "4a174747a1982bf39059d682f67c7c5aa5d5de42",
            "path": "plans/035-mlb-pitcher-skill-challenger.md",
            "byte_offset": 1089,
            "line_sha256": "395d4446ea2e60f45b530d950ff292cad06507c5f29f0a592a304a877f4243a9",
            "classification": "governance_text"
          },
          {
            "object_id": "4ac806f4e6ad4ac5fc58134b8cf3a46b9ab461a1",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2617,
            "line_sha256": "fa505acbf58f65b881a4af07ce308fa5366af9e003f8843c383410af7048048c",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "4c48e60c65fd4f46c4278d91ff120b7c39caf3e2",
            "path": "docs/superpowers/plans/2026-08-02-mlb-pitcher-skill-challenger.md",
            "byte_offset": 3139,
            "line_sha256": "ca204326600d3a5b94583a2327dbe8f66324c145af9265b07a1a826377c3c6d2",
            "classification": "governance_text"
          },
          {
            "object_id": "52d884797f44b6c7a66a787fbcaa294e8438b64a",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 6859,
            "line_sha256": "e3033c0989c9c1c1a26d302d226523630ab6475d8de0828a7f298be765675fc4",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "52d884797f44b6c7a66a787fbcaa294e8438b64a",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 8234,
            "line_sha256": "1c5ec6eabc6b83a5d7c82536e977727d26364bf21cab62c41ec75e695aedcd0e",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "547851c6e641133862ecebf0270b6015e263fd53",
            "path": "docs/registration-2026-08-14-stage1-maturation-rerun.md",
            "byte_offset": 4346,
            "line_sha256": "4da1651d36e863d9dff4997f40d95f4205a44353affb6a2c82377c33121af28b",
            "classification": "governance_text"
          },
          {
            "object_id": "5a3208e2f9ccc2b1c6e6f38699759e6b3faf8d20",
            "path": "data/prediction_archive/valucast_prospect_rank_v1/2026-06-26.json",
            "byte_offset": 443320,
            "line_sha256": "3f9a58d006edc1a7ee9f9877c252a2dd392930771bac72454678de7c32c2617b",
            "classification": "unrelated_numeric_data"
          },
          {
            "object_id": "64e12e9bf5bebacde2bbede9667ef305cadb51ae",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 7041,
            "line_sha256": "e3033c0989c9c1c1a26d302d226523630ab6475d8de0828a7f298be765675fc4",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "64e12e9bf5bebacde2bbede9667ef305cadb51ae",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 8416,
            "line_sha256": "1c5ec6eabc6b83a5d7c82536e977727d26364bf21cab62c41ec75e695aedcd0e",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "6bcc3cb441024581efd538f69dd6e4595f4e5879",
            "path": "docs/superpowers/specs/2026-07-20-prospect-proof-foundation-v2-design.md",
            "byte_offset": 10746,
            "line_sha256": "37cbe1f1d8dded126e7f872a49e4cf5b48df43b22b3f165c703a83eefd0851ca",
            "classification": "governance_text"
          },
          {
            "object_id": "813744d0506a493f072367f1466acd1de46b26ec",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 7041,
            "line_sha256": "e3033c0989c9c1c1a26d302d226523630ab6475d8de0828a7f298be765675fc4",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "813744d0506a493f072367f1466acd1de46b26ec",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 8416,
            "line_sha256": "1c5ec6eabc6b83a5d7c82536e977727d26364bf21cab62c41ec75e695aedcd0e",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "8217751592a7c3366f687251622be03a21d10bd9",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2604,
            "line_sha256": "739c1e1ac532afa006b248553b7b458ca775fa9b3591bd5e4e4e03b50cf44f50",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "873bf7dfb53cb9581a3bdfb29bbb366f97b2f01b",
            "path": "prospects/challenger_eval.py",
            "byte_offset": 640,
            "line_sha256": "e82be979672a575ea35b9955488f7deff5c2110cb17a76d7f940b28b20935f66",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "8ef51a8053faa9b11a194a693a1b383a74f440b9",
            "path": "docs/superpowers/plans/2026-07-20-prospect-proof-foundation-v2.md",
            "byte_offset": 2418,
            "line_sha256": "ac494f17044e0049d7aa41a070c925532529a8d9cea56f679fdac002420c31b4",
            "classification": "governance_text"
          },
          {
            "object_id": "8ef51a8053faa9b11a194a693a1b383a74f440b9",
            "path": "docs/superpowers/plans/2026-07-20-prospect-proof-foundation-v2.md",
            "byte_offset": 20829,
            "line_sha256": "4c64ea71bf53b1dd820a21b294c921d443167bb5912e68a3adcac60dbc7cb26b",
            "classification": "governance_text"
          },
          {
            "object_id": "8ef51a8053faa9b11a194a693a1b383a74f440b9",
            "path": "docs/superpowers/plans/2026-07-20-prospect-proof-foundation-v2.md",
            "byte_offset": 21477,
            "line_sha256": "e82be979672a575ea35b9955488f7deff5c2110cb17a76d7f940b28b20935f66",
            "classification": "governance_text"
          },
          {
            "object_id": "8ef51a8053faa9b11a194a693a1b383a74f440b9",
            "path": "docs/superpowers/plans/2026-07-20-prospect-proof-foundation-v2.md",
            "byte_offset": 38238,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "8fbd3266cfc0893754cd2a45578d9356b07f69d8",
            "path": "plans/README.md",
            "byte_offset": 30176,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "960f01456f6f175bc762044dd6037d11dffb69ca",
            "path": "tests/test_level_translation_challenger.py",
            "byte_offset": 10514,
            "line_sha256": "24a206ffd07da717f3f476a37cc907fe45720e326c95ade6fb61566cd5f0d3d8",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "99aac2ca7210837b3edf142bf3875cfe361d4c6c",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "9a23cbe3a1cd3ae31ad28a9230e16bd8ebe2fde8",
            "path": "docs/registration-2026-08-14-stage1-maturation-rerun.md",
            "byte_offset": 5007,
            "line_sha256": "4da1651d36e863d9dff4997f40d95f4205a44353affb6a2c82377c33121af28b",
            "classification": "governance_text"
          },
          {
            "object_id": "9c6bccb0426e2fc11774fc431b934a36b50ea749",
            "path": "plans/033-prospect-normalized-production-gate.md",
            "byte_offset": 3288,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "a65406f00ec402a63e6d0994ec550d407f6dd3b4",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "a87056b22706a390ae91d9609141dbeb591d91fd",
            "path": "data/public/public_dynasty_snapshot.json",
            "byte_offset": 2748165,
            "line_sha256": "cdc4c60ef9f21628d8e93919685919e92c43276e8e0d69ad7c8a1107d261ebef",
            "classification": "unrelated_numeric_data"
          },
          {
            "object_id": "a9edd145c264af20595d189208447806290e234f",
            "path": "tests/test_prospect_challenger_eval.py",
            "byte_offset": 7895,
            "line_sha256": "4c64ea71bf53b1dd820a21b294c921d443167bb5912e68a3adcac60dbc7cb26b",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "b06954584926a839c4efb5ddb45ad30872560548",
            "path": "plans/README.md",
            "byte_offset": 30591,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "b4ad32a174432f963ebe87ce1b587bab5a690b5f",
            "path": "data/models/valucast_prospect_rank_v1.json",
            "byte_offset": 1057156,
            "line_sha256": "cdc4c60ef9f21628d8e93919685919e92c43276e8e0d69ad7c8a1107d261ebef",
            "classification": "unrelated_numeric_data"
          },
          {
            "object_id": "b7ba455b61f660ac046390b5fbb9a7580e30a613",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "b93398cc1ed73fe304b94ea6d652b785c3b1f4cb",
            "path": "data/validation/level_translation_dryrun.json",
            "byte_offset": 9697,
            "line_sha256": "10285d65023afa743e429ac66da7a9c07344ede217454dead418db9c2d41b072",
            "classification": "negative_execution_note"
          },
          {
            "object_id": "bfd6e96d0b0f1ae360f52969ff3281c3b1559875",
            "path": "scripts/run_stage1_maturation_rerun.py",
            "byte_offset": 1780,
            "line_sha256": "ca17176af90ef9ce651f345d0d815eb6b396f0692d6dbe6fb519315b61d4e8d6",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "c048a6fdf06b9a1680af98a183e82ae87dc906c4",
            "path": "plans/README.md",
            "byte_offset": 30148,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "c0eab96da6fd347929492d3e6f9c585d74586c23",
            "path": "plans/033-prospect-normalized-production-gate.md",
            "byte_offset": 6560,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "c231a9ca3c55b082f840d8e0ba7b355afdae218f",
            "path": "scripts/run_level_translation_dryrun.py",
            "byte_offset": 1451,
            "line_sha256": "ced2924e3779ea916bd56289153842483966f81f69f92bca268f8489aecd9a13",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "c231a9ca3c55b082f840d8e0ba7b355afdae218f",
            "path": "scripts/run_level_translation_dryrun.py",
            "byte_offset": 3838,
            "line_sha256": "10abfcb4f500638081acfcbd8f90887f6114bc9dbe6a7516818a24c9385e7dea",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "c231a9ca3c55b082f840d8e0ba7b355afdae218f",
            "path": "scripts/run_level_translation_dryrun.py",
            "byte_offset": 3910,
            "line_sha256": "b69937c61ebee2b50a432a9bdbf6378180cd25e41ef6e5cab5e2754bd8f75bb4",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "c231a9ca3c55b082f840d8e0ba7b355afdae218f",
            "path": "scripts/run_level_translation_dryrun.py",
            "byte_offset": 19316,
            "line_sha256": "5df9329516aaf727bc82d19e485385d4cbc974bc37a815c056575fcb769ad1e7",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "c25fd8c47e881bf51780b3ba5007ffd653e1be66",
            "path": "plans/035-mlb-pitcher-skill-challenger.md",
            "byte_offset": 1089,
            "line_sha256": "395d4446ea2e60f45b530d950ff292cad06507c5f29f0a592a304a877f4243a9",
            "classification": "governance_text"
          },
          {
            "object_id": "c47a508ddfc57de97dd6a80e961c47c843aefe3e",
            "path": "docs/superpowers/specs/2026-07-20-prospect-proof-foundation-v2-design.md",
            "byte_offset": 10584,
            "line_sha256": "37cbe1f1d8dded126e7f872a49e4cf5b48df43b22b3f165c703a83eefd0851ca",
            "classification": "governance_text"
          },
          {
            "object_id": "c65e51410b54d451b3e6410c47d67933dfb7a815",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2617,
            "line_sha256": "fa505acbf58f65b881a4af07ce308fa5366af9e003f8843c383410af7048048c",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "c980c3cf2e0a8f35e28a964e1fe6b6b659a02900",
            "path": "tests/fixtures/prospect_v23_registration_static_preimage.json",
            "byte_offset": 2889,
            "line_sha256": "9daea53fd7d0120978309ce292bd0d9e34ed6ce7b739a730baefe492cb40d155",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "c9a4ee8c5d50e2d4204a1f2e08927892d0fc7496",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 7042,
            "line_sha256": "e3033c0989c9c1c1a26d302d226523630ab6475d8de0828a7f298be765675fc4",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "c9a4ee8c5d50e2d4204a1f2e08927892d0fc7496",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 8620,
            "line_sha256": "1c5ec6eabc6b83a5d7c82536e977727d26364bf21cab62c41ec75e695aedcd0e",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "cd525d22246016b3f7baa2ec421e6ecd20e9f3ab",
            "path": "plans/033-prospect-normalized-production-gate.md",
            "byte_offset": 7468,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "d07b9ee1f55017bae0313c2894490c6701217d98",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2617,
            "line_sha256": "fa505acbf58f65b881a4af07ce308fa5366af9e003f8843c383410af7048048c",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "d0b97505b8e7c9dc98043a1c2f8cdd5247bb99c9",
            "path": "plans/033-prospect-normalized-production-gate.md",
            "byte_offset": 7438,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "dac799fca7fe91f874e558ca33d757e83ca2fda9",
            "path": "docs/superpowers/plans/2026-08-20-prospect-rank-vnext-phase-a.md",
            "byte_offset": 58697,
            "line_sha256": "49bc95dce1a6958c2e5b31fb2418980d50bb4ade138c633e6f9e09732bcd555d",
            "classification": "governance_text"
          },
          {
            "object_id": "dac799fca7fe91f874e558ca33d757e83ca2fda9",
            "path": "docs/superpowers/plans/2026-08-20-prospect-rank-vnext-phase-a.md",
            "byte_offset": 58843,
            "line_sha256": "bc0b818073c1e12a0546343704600a4adfd895f2023b8e2bea1fb7f401e5cea1",
            "classification": "governance_text"
          },
          {
            "object_id": "de93ac5eaa961231a9ec5f517060f095e6763c9c",
            "path": "plans/README.md",
            "byte_offset": 30604,
            "line_sha256": "1c11da2c8af3ff736e958825bd0e5bc8c89d258e24bc74f0fa7544227bbc0248",
            "classification": "governance_text"
          },
          {
            "object_id": "e200b1b103f4fd2ecdfa659abd9764d5d4c948ff",
            "path": "tests/fixtures/prospect_v23_registration_static_preimage.json",
            "byte_offset": 2889,
            "line_sha256": "9daea53fd7d0120978309ce292bd0d9e34ed6ce7b739a730baefe492cb40d155",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "e437a2a528bb5ee94248ea1bc5510de6b540a311",
            "path": "docs/program-2026-08-14-pitcher-pass.md",
            "byte_offset": 768,
            "line_sha256": "1c35e18daa05e36f13aa9f764675ded703ebad110d7b93c50a55e18a26e5ab92",
            "classification": "governance_text"
          },
          {
            "object_id": "e58cf7994db4e90e138d0c2b1c222663441893ae",
            "path": "plans/033-prospect-normalized-production-gate.md",
            "byte_offset": 7468,
            "line_sha256": "6f222bcdea0f1b73b72337e33ac157ec82ba4882746d277a890d5817025d9b88",
            "classification": "governance_text"
          },
          {
            "object_id": "e95cc51f82da7a41644a007e4143e568b64e1780",
            "path": "docs/superpowers/specs/2026-07-20-prospect-proof-foundation-v2-design.md",
            "byte_offset": 10746,
            "line_sha256": "37cbe1f1d8dded126e7f872a49e4cf5b48df43b22b3f165c703a83eefd0851ca",
            "classification": "governance_text"
          },
          {
            "object_id": "eb6bf9d1c5311e2e6f0167a4cb3fc2ad32864f29",
            "path": "prospects/challenger_eval.py",
            "byte_offset": 986,
            "line_sha256": "e82be979672a575ea35b9955488f7deff5c2110cb17a76d7f940b28b20935f66",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "ed3372601d3eee4ccfdc9598d93302527e97518a",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 6001,
            "line_sha256": "e3033c0989c9c1c1a26d302d226523630ab6475d8de0828a7f298be765675fc4",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "ed3372601d3eee4ccfdc9598d93302527e97518a",
            "path": "tests/test_prospect_normalized_production_registration.py",
            "byte_offset": 7376,
            "line_sha256": "1c5ec6eabc6b83a5d7c82536e977727d26364bf21cab62c41ec75e695aedcd0e",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "eeb8a98af109100edeae985be31336a6a4ca2594",
            "path": "plans/034-post-2026-prospect-challenger-epoch.md",
            "byte_offset": 7330,
            "line_sha256": "bbeb5aa19613503d4b43b0d9109f4c8bca6b3d2d56e093b2613f3793499298d5",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 134,
            "line_sha256": "d317685b5d962633e5f58bace45ea8eed422e92a53422b1abc477b25f5eaf363",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 534,
            "line_sha256": "a507a4b05ec5a535b8a3600beaeb33475cfd0d1463f86918cedd46548d617bf4",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 7640,
            "line_sha256": "811e3b0cd996db5883fc1a9f799f3517a0f2005ae987138767aba7028b5ec22f",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 7921,
            "line_sha256": "29a45febb61080c441460adfef6d1bb124a2c20329476e57a8301f51daa5c143",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 8079,
            "line_sha256": "a4568c8df6a298853189d43d88004544147f550e0fa44ddb34f5b5c42dd31b21",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 10030,
            "line_sha256": "f201587929a20b387c07aeb19e5fc3e29b28bd30ecb1d7243a7bf0638b940773",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 12085,
            "line_sha256": "043b2cbabfd46f9a436fc726c435859576dad0febf4b3c6358c31fa7c33d92a5",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 15849,
            "line_sha256": "fdd40d9682b79faec0f7081e000d38e60567944a3f9bb0914edc213ac1a33e4b",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 16809,
            "line_sha256": "c8fa682a15c6e2fdee66b8cf29db5dd0ac1eafefa4c43a6acf3a4f1d5f48364b",
            "classification": "governance_text"
          },
          {
            "object_id": "efd7c00558581915a32a76c171ddfe74357731a3",
            "path": "plans/031-pitcher-strike-pct-gate.md",
            "byte_offset": 17232,
            "line_sha256": "5a2e741228c20e701cebd6bd89f52956d050b8bf33d8beb0cad24f827316c1fa",
            "classification": "governance_text"
          },
          {
            "object_id": "f2c2d400e59d8a2df3f5728cc36ad3590ad51c1c",
            "path": "docs/superpowers/specs/2026-07-20-prospect-proof-foundation-v2-design.md",
            "byte_offset": 10746,
            "line_sha256": "37cbe1f1d8dded126e7f872a49e4cf5b48df43b22b3f165c703a83eefd0851ca",
            "classification": "governance_text"
          },
          {
            "object_id": "f7ee020381c701d9d809e153c136cf8917e81a00",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2617,
            "line_sha256": "fa505acbf58f65b881a4af07ce308fa5366af9e003f8843c383410af7048048c",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "fc331d1de1dcd042271b1465b1657c354ba17585",
            "path": "data/public/public_dynasty_snapshot.json",
            "byte_offset": 2755971,
            "line_sha256": "cdc4c60ef9f21628d8e93919685919e92c43276e8e0d69ad7c8a1107d261ebef",
            "classification": "unrelated_numeric_data"
          },
          {
            "object_id": "fd3b409f1162d3dda18f74bb20978b2591181b01",
            "path": "data/models/valucast_prospect_rank_v1.json",
            "byte_offset": 1055270,
            "line_sha256": "cdc4c60ef9f21628d8e93919685919e92c43276e8e0d69ad7c8a1107d261ebef",
            "classification": "unrelated_numeric_data"
          }
        ],
        "classification_sha256": "987530729f55cbeffb732243c37631a8ff3ddbd250ee8d0ae126311ac19f3411",
        "result_artifact_entries": [],
        "runner_invocation_entries": []
      }
    },
    "plan_034": {
      "plan_path": "plans/034-post-2026-prospect-challenger-epoch.md",
      "track": "model_track",
      "transition": "superseded_by_plan_038",
      "held_seed": 34021,
      "seed_status": "retired_unspent_never_execute",
      "pre_transition_blob": "eeb8a98af109100edeae985be31336a6a4ca2594",
      "post_transition_blob": "86cf6b0b6a41ac8504b2ace98a011fb68217ffa3",
      "append_only_prefix_bytes": 11847,
      "originating_latest_commit": "b6172e2912f6a7b46af55c6417c8af66eb8c2586",
      "registered_json_raw_body_sha256": "c36e9656ba7126e41b81ebbf854785ce3f978582912b99e496ca76be0f108dd9",
      "parsed_registration_canonical_sha256": "a7fbb5912ae5620563ea4493db6cac0679730da5e69b0a5d37e6eb616b919ec4",
      "active_tracks": {
        "buy_momentum": {
          "value": {
            "status": "registered_family_not_executable",
            "hypothesis": "audit_asymmetric_buy_momentum_prior",
            "primary": "forward_registered_buy_decision_regret",
            "must_use_preexisting_forward_cohorts": true,
            "cannot_change_rank_or_value_in_this_protocol": true,
            "seed": 34027
          },
          "canonical_sha256": "ecca3d3964da2daac195d2825d6f5850ff1956f8800e4cbd4f37a540aa6053b7"
        },
        "cross_universe_mapping": {
          "value": {
            "status": "registered_family_not_executable",
            "hypothesis": "genuine_empirical_mlb_to_prospect_value_mapping",
            "control": "compatibility_only_no_unit_mapping",
            "primary": "forward_format_specific_trade_decision_regret",
            "minimum_completed_cohorts": 4,
            "cannot_change_display_or_value_in_this_protocol": true,
            "seed": 34031
          },
          "canonical_sha256": "0076afb20765bfc44d5f1f58f726b68cafa872397ba3f0efedbe1a8bef783412"
        }
      },
      "history_evidence": {
        "scope_tip": "e1229bacc1c64d651609a5e621de0ec528a79a78",
        "standalone_pattern": "(^|[^0-9])34021([^0-9]|$)",
        "inventory_schema": "git_blob_path_offset_v1",
        "object_count": 25964,
        "sorted_object_ids_sha256": "338ecf8463398b9702b9963475a99cb18d160f6a730d64d8a66fcc621484a35c",
        "inventory_entry_count": 25,
        "inventory_sha256": "6fffbff002d1d2582317a12820d5e65beec9c5416e2754139a948f121127e0f2",
        "classification_schema": "git_blob_path_offset_line_sha256_classification_v1",
        "classifications": [
          {
            "object_id": "0db5b5e08a7abdeacf17975484a0c08c12b617d2",
            "path": "tests/test_mlb_pitcher_skill_registration.py",
            "byte_offset": 237,
            "line_sha256": "656e292f58cc81b528b98b4c7283a39d9b79a014193d585788b30126b4ba511d",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "17fec82ade1e72dee5250ae96fae41200d209059",
            "path": "tests/fixtures/prospect_v23_registration_static_preimage.json",
            "byte_offset": 3807,
            "line_sha256": "e0a0e51b45a4ed54a8081fa67baf9313d978d69e0633ae9aa58a99d792c7ed7d",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "29f97833e51725e9db9ee6ec5693fad4c15ce616",
            "path": "plans/README.md",
            "byte_offset": 33392,
            "line_sha256": "2c66f44c5aa0000f23989845355be1635bda3ff895cdbdf9d8ab15378606a24a",
            "classification": "governance_text"
          },
          {
            "object_id": "414daa0e3de62c00f6cd28fb3ccea614f5461003",
            "path": "plans/README.md",
            "byte_offset": 32964,
            "line_sha256": "2c66f44c5aa0000f23989845355be1635bda3ff895cdbdf9d8ab15378606a24a",
            "classification": "governance_text"
          },
          {
            "object_id": "4401b9929d55bc80df2b2907aea48982032d7f50",
            "path": "plans/034-post-2026-prospect-challenger-epoch.md",
            "byte_offset": 7255,
            "line_sha256": "0a0474ee34f584c85db6dd6fda4ef60261b7828eb4412a1732ec139bb84c5dad",
            "classification": "governance_text"
          },
          {
            "object_id": "4a174747a1982bf39059d682f67c7c5aa5d5de42",
            "path": "plans/035-mlb-pitcher-skill-challenger.md",
            "byte_offset": 1117,
            "line_sha256": "395d4446ea2e60f45b530d950ff292cad06507c5f29f0a592a304a877f4243a9",
            "classification": "governance_text"
          },
          {
            "object_id": "4ac806f4e6ad4ac5fc58134b8cf3a46b9ab461a1",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2668,
            "line_sha256": "ca5ba6bc1d42d68b01ecebe3299486acb80b9647e4ea3f9245eb57976a72b690",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "4c48e60c65fd4f46c4278d91ff120b7c39caf3e2",
            "path": "docs/superpowers/plans/2026-08-02-mlb-pitcher-skill-challenger.md",
            "byte_offset": 3175,
            "line_sha256": "ca204326600d3a5b94583a2327dbe8f66324c145af9265b07a1a826377c3c6d2",
            "classification": "governance_text"
          },
          {
            "object_id": "547851c6e641133862ecebf0270b6015e263fd53",
            "path": "docs/registration-2026-08-14-stage1-maturation-rerun.md",
            "byte_offset": 4376,
            "line_sha256": "5eb38f1f3d2a8622c30b77cc1434d8114f0d35dfa3eabbebb08e8ba3161942b1",
            "classification": "governance_text"
          },
          {
            "object_id": "8217751592a7c3366f687251622be03a21d10bd9",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2643,
            "line_sha256": "739c1e1ac532afa006b248553b7b458ca775fa9b3591bd5e4e4e03b50cf44f50",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "8fbd3266cfc0893754cd2a45578d9356b07f69d8",
            "path": "plans/README.md",
            "byte_offset": 32964,
            "line_sha256": "2c66f44c5aa0000f23989845355be1635bda3ff895cdbdf9d8ab15378606a24a",
            "classification": "governance_text"
          },
          {
            "object_id": "99aac2ca7210837b3edf142bf3875cfe361d4c6c",
            "path": "plans/README.md",
            "byte_offset": 33390,
            "line_sha256": "cf79170ce4c2893809b4e49307ffe467966cb53ce90ffd6383dbc5f1dd2f3de1",
            "classification": "governance_text"
          },
          {
            "object_id": "9a23cbe3a1cd3ae31ad28a9230e16bd8ebe2fde8",
            "path": "docs/registration-2026-08-14-stage1-maturation-rerun.md",
            "byte_offset": 5037,
            "line_sha256": "5eb38f1f3d2a8622c30b77cc1434d8114f0d35dfa3eabbebb08e8ba3161942b1",
            "classification": "governance_text"
          },
          {
            "object_id": "bfd6e96d0b0f1ae360f52969ff3281c3b1559875",
            "path": "scripts/run_stage1_maturation_rerun.py",
            "byte_offset": 1816,
            "line_sha256": "66be5ec3c39dc4c598be5ba5a362eea75d38a27412954945e543311ec792b5d4",
            "classification": "forbidden_seed_guard"
          },
          {
            "object_id": "c048a6fdf06b9a1680af98a183e82ae87dc906c4",
            "path": "plans/README.md",
            "byte_offset": 32936,
            "line_sha256": "2c66f44c5aa0000f23989845355be1635bda3ff895cdbdf9d8ab15378606a24a",
            "classification": "governance_text"
          },
          {
            "object_id": "c25fd8c47e881bf51780b3ba5007ffd653e1be66",
            "path": "plans/035-mlb-pitcher-skill-challenger.md",
            "byte_offset": 1117,
            "line_sha256": "395d4446ea2e60f45b530d950ff292cad06507c5f29f0a592a304a877f4243a9",
            "classification": "governance_text"
          },
          {
            "object_id": "c65e51410b54d451b3e6410c47d67933dfb7a815",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2668,
            "line_sha256": "ca5ba6bc1d42d68b01ecebe3299486acb80b9647e4ea3f9245eb57976a72b690",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "c980c3cf2e0a8f35e28a964e1fe6b6b659a02900",
            "path": "tests/fixtures/prospect_v23_registration_static_preimage.json",
            "byte_offset": 3807,
            "line_sha256": "e0a0e51b45a4ed54a8081fa67baf9313d978d69e0633ae9aa58a99d792c7ed7d",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "ce7d3f0be0f7268ec3ff112682f7738cbddb6f65",
            "path": "data/models/valucast_scouting_llm_cache.json",
            "byte_offset": 1188224,
            "line_sha256": "efd74fa2c60b5a63f5dc7b5f155894e7f65b46fc4580e33cf9ee37ee545ca310",
            "classification": "unrelated_numeric_data"
          },
          {
            "object_id": "d07b9ee1f55017bae0313c2894490c6701217d98",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2668,
            "line_sha256": "ca5ba6bc1d42d68b01ecebe3299486acb80b9647e4ea3f9245eb57976a72b690",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "dac799fca7fe91f874e558ca33d757e83ca2fda9",
            "path": "docs/superpowers/plans/2026-08-20-prospect-rank-vnext-phase-a.md",
            "byte_offset": 58973,
            "line_sha256": "085f2abb83566ca96d2ecbe05de504bce50decde0aa28a95c887be2230ef4650",
            "classification": "governance_text"
          },
          {
            "object_id": "dac799fca7fe91f874e558ca33d757e83ca2fda9",
            "path": "docs/superpowers/plans/2026-08-20-prospect-rank-vnext-phase-a.md",
            "byte_offset": 59096,
            "line_sha256": "86d87bb4ef13a618776d8894f2d99378c722db2494c0dba4a98cfaaa67b90bdf",
            "classification": "governance_text"
          },
          {
            "object_id": "e200b1b103f4fd2ecdfa659abd9764d5d4c948ff",
            "path": "tests/fixtures/prospect_v23_registration_static_preimage.json",
            "byte_offset": 3807,
            "line_sha256": "e0a0e51b45a4ed54a8081fa67baf9313d978d69e0633ae9aa58a99d792c7ed7d",
            "classification": "test_guard_or_fixture"
          },
          {
            "object_id": "eeb8a98af109100edeae985be31336a6a4ca2594",
            "path": "plans/034-post-2026-prospect-challenger-epoch.md",
            "byte_offset": 7259,
            "line_sha256": "0a0474ee34f584c85db6dd6fda4ef60261b7828eb4412a1732ec139bb84c5dad",
            "classification": "governance_text"
          },
          {
            "object_id": "f7ee020381c701d9d809e153c136cf8917e81a00",
            "path": "tests/test_prospect_v23_development.py",
            "byte_offset": 2668,
            "line_sha256": "ca5ba6bc1d42d68b01ecebe3299486acb80b9647e4ea3f9245eb57976a72b690",
            "classification": "test_guard_or_fixture"
          }
        ],
        "classification_sha256": "bbf86755a4e072587c2dc804120b394d183627f11c2b333ec9a000d2b8937b23",
        "result_artifact_entries": [],
        "runner_invocation_entries": []
      }
    },
    "old_local_v2_3": {
      "design_commit": {
        "commit": "027a6efa7d432a6a466d2ca4d37c28e7abd9da1c",
        "status": "superseded_unspent",
        "execution_status": "retired_never_execute"
      },
      "plan_commit": {
        "commit": "1201b799eb4c73f69d5191167cb7a0494fadceca",
        "status": "superseded_unspent",
        "execution_status": "retired_never_execute"
      }
    },
    "plan_index": {
      "plan_path": "plans/README.md",
      "transition": "update_plan_031_plan_034_model_track_status_and_add_plan_038",
      "pre_transition_blob": "8fbd3266cfc0893754cd2a45578d9356b07f69d8",
      "post_transition_blob": "afd9c58efa37f2a6b495e3de6909ebdd69d332f0"
    }
  },
  "inputs": {
    "data/validation/valucast_prospect_v2_development_contract.json": {
      "git_blob": "2bd549347227235061c51444fdd709bd69153dee",
      "canonical_sha256": "df573b47d652eed14b8289919dbe2696cd7c9b96bd68c678fc124dabfa5a92b3",
      "internal_field": "input_sha256",
      "internal_sha256": "df573b47d652eed14b8289919dbe2696cd7c9b96bd68c678fc124dabfa5a92b3"
    },
    "data/models/valucast_prospect_model_v0_9.json": {
      "git_blob": "788ba04a054474430a4cdb01e3ac783795cfa088",
      "canonical_sha256": "90b8c303f011c48a4806aa8300d949e85ecb82999bf975ce5d3d3320c7f59663",
      "internal_field": "artifact_sha256",
      "internal_sha256": "048876c0f64365ae9960a3b1987558c9e190f4c2eec87b743bb52f2fd4146c4e"
    },
    "data/validation/valucast_prospect_rank_v2_1_development.json": {
      "git_blob": "195febb61a0867da213d2fca096d02e58289a218",
      "canonical_sha256": "a0b1fd17a08aa4b6d64854ee5a9ef92df79f6e76fd1aa4ae2de6a4d3d81dd7ba",
      "internal_field": "artifact_sha256",
      "internal_sha256": "cb2c518da530acf20d50766d1925eff6da52193227e15569c7479120e2c998db"
    },
    "data/validation/valucast_prospect_rank_v2_2_development.json": {
      "git_blob": "44e7d8a26259f06cdc9b5cfa5c48c9b5c9c4b214",
      "canonical_sha256": "fa9b58a55a3d950c52b8a23aeeb14ebf6d3731b873e9c4b2028ffd23f66b4178",
      "internal_field": "artifact_sha256",
      "internal_sha256": "9fc70d71e8d3cefa76506748c5dc9caa46ac083692320d2164ac137a95855191"
    }
  },
  "sources": {
    "mlb/availability.py": {
      "git_blob": "a046e8d56d3391aeb452caf462fb63c509ae25de",
      "normalized_sha256": "0cc0fcf7b2dfa1feee66f4de0e0b0e3a6e612a33ebe8c84f33f484a646465fae"
    },
    "mlb/__init__.py": {
      "git_blob": "d382c58d3c9a8a690a5ed1038f0861f0262fc9c4",
      "normalized_sha256": "ea3a37a59929ae4b2b07cc45417e424d6e360f0d94e2a05dc5c03c0291c6a863"
    },
    "mlb/roster_status.py": {
      "git_blob": "69652cd1dbf3714c02ab6ac83e08dac1259738b5",
      "normalized_sha256": "08951a2c1dec4809c87553cf540c6e1e209e5548923039cac2682dc8d5d7f2d4"
    },
    "prospects/__init__.py": {
      "git_blob": "4ee21cda3b1f3acc0615201beac5a4b615f357fc",
      "normalized_sha256": "b8c5fb6459064582f37159e97d3f93ffcc48151377ac77463513455b79f9e94e"
    },
    "prospects/ahead_of_consensus.py": {
      "git_blob": "fb299154f5330b6596a388df52b24a6c37a5efa6",
      "normalized_sha256": "bc355d41cf3185b5bbbf0f9012ee910371eb31e99183e414deae34d461cfcabe"
    },
    "prospects/availability.py": {
      "git_blob": "60e7b20f28ecde3831d3fe48f68c27e7a9d3c93c",
      "normalized_sha256": "ca76ccbf229f1da4403649f34cac72015c3ba04156ba3705faa75ba792b3c21d"
    },
    "prospects/cross_role_calibration.py": {
      "git_blob": "bd83d626b8e039f3202e72ccf8c06a98fb7a3899",
      "normalized_sha256": "914d87cc33304619471792ba95a32af22140f666b92fd14fab97a0fa7863f73b"
    },
    "prospects/dynasty.py": {
      "git_blob": "b8c63d26084ff702f2a75a57a7299291da4583b8",
      "normalized_sha256": "e25b8ec848d39006d0a057f4d74288c9b5a65b96781e5c996ad9e0855aa459d9"
    },
    "prospects/dynasty_backtest.py": {
      "git_blob": "6a42cc91f50025a39737e5dd2b1bae6cf9bd6fe2",
      "normalized_sha256": "4e895c2a78dac030e4ccf537087a54404f47dde94095d1a4ff8bd21d49fe08c9"
    },
    "prospects/gate.py": {
      "git_blob": "dd6e22aae744918b4d6e9ebc5c4625e32cd30f0b",
      "normalized_sha256": "10bc963ba9aab57f73db512d92089112c2644534772fb6b02fac67085bb2abc9"
    },
    "prospects/impact_oof.py": {
      "git_blob": "1e958652d14ed0e75c508d0d4c478637c6a944ff",
      "normalized_sha256": "24183e9a631bee16ce355bb679a39923e5207b1f746a27dd9fba2e37c1fffc5c"
    },
    "prospects/input_contract.py": {
      "git_blob": "caab4452a031b1312e3a1460bf01008e9a3e3de2",
      "normalized_sha256": "208e522b5741b51a15b0e0cdb269da54540a90deef23000fd85d624488b920f5"
    },
    "prospects/level_translation_challenger.py": {
      "git_blob": "c240c9f3cafe38b0c8f6b91f24b676e1e3e177f0",
      "normalized_sha256": "18cf35ae6495947dce1bfc237c7fa92bdf52b2a235651b1be9b1de0a5cfcfbe9"
    },
    "prospects/milb_translation.py": {
      "git_blob": "ed65560f9ab66ccbe0f3a0daf5b8c2a5be11e89e",
      "normalized_sha256": "3b7c78c02b935a2b1a72b06e0a9991392e26e6270153817d9a2c36ceeae49ffe"
    },
    "prospects/model.py": {
      "git_blob": "5ea6d54da1928684e0e024b84de766602c4bfc8e",
      "normalized_sha256": "ca8060591b65fc4b8a0a39c417201c09918630c3cad9c1ec2a3b3e50d52b8ada"
    },
    "prospects/ordinal_calibration_power.py": {
      "git_blob": "d7f52c666e4d8f64fed0132410a8b17646a29105",
      "normalized_sha256": "aaa82a377fe837b6bd27fed8aec77cd73daab25f61becbf65e87b5566a4a6ba2"
    },
    "prospects/outcome_oof.py": {
      "git_blob": "104692f2f4c21779196dd0a561fccd15f8053147",
      "normalized_sha256": "1f99d9e0a57abe84f4e668e9f83f0d54f0b646ca485c21a648bdd62c2e6aee6e"
    },
    "prospects/pitcher_challenger.py": {
      "git_blob": "862f1e11c17a6d6f2e326f24c2c05a7d7d20ef2c",
      "normalized_sha256": "e61b36b05994017513d1c7968e8cc91ce3e25a619dcc67bdaaa35e8792fa966d"
    },
    "prospects/probability_reliability.py": {
      "git_blob": "f6da2ff8abe5b3642ea7646ec3f02477d98d0dad",
      "normalized_sha256": "86a7d4aaca1df86c0c59b8156f1d24fb53ced1b68fb2fc44c679cc22f3e3e652"
    },
    "prospects/prospect_v09.py": {
      "git_blob": "592d1fbc93e4bb0b13a10fae87507116acdb41c9",
      "normalized_sha256": "da56390d9c53c577cdf6ea070f16f106616da44874b8ea32b678210a35450dad"
    },
    "prospects/prospect_v2_candidate.py": {
      "git_blob": "e81583a336d6f64089887b0f3bdbefa38eb63909",
      "normalized_sha256": "7baa179c66fa6855272b3e0419ccbf1f8990450c87fc5f31990a2983c8fdcacc"
    },
    "prospects/prospect_v2_target.py": {
      "git_blob": "abb5b89bff8d41ca9079c2389f0da9a17eaf284b",
      "normalized_sha256": "d76b74ca7217fd6577d5149b253990b37690b74f2038e148d5a4ea9fea4ee39b"
    },
    "prospects/rank_backtest.py": {
      "git_blob": "edc0813e338f1a89a36f5b09f1b7f8ed24c78e20",
      "normalized_sha256": "43d24e9fb073bcbca5a59e23abf4d216988e3a2eabdf119aaea1cc36abe246a7"
    },
    "prospects/rank_v1.py": {
      "git_blob": "92434dd034f8a2699ea38bcc2b2b5b7a6488e55d",
      "normalized_sha256": "7d5a33feb90ed5fcc0bfe9955cea24a00fc300daef2bbb2e25ffb170131ebe2e"
    },
    "prospects/rank_v2.py": {
      "git_blob": "5907fe49246dc247eb777bfaab5fbcd2b3cb6d31",
      "normalized_sha256": "8f8435217fce43e77ae6b64115b04b36413d89cea53daab29a49108eb70261f2"
    },
    "prospects/role_slope_joint_calibration.py": {
      "git_blob": "74ad3651db3049ab1889538b45f7d275bbd1a34e",
      "normalized_sha256": "bc96e0e2bcc77713f00215cdb25beb6a4bfc8f2c306131d6917eda4088106cbc"
    },
    "prospects/stage1_contract.py": {
      "git_blob": "ce8ef455822f8992839ff492977a41ab24eba83f",
      "normalized_sha256": "330cfc468ec095e5e9309362ed3d3ea68e48ee9e371ea107689f941a73d28be8"
    },
    "prospects/stage1_outcome_proof.py": {
      "git_blob": "73a614e748b84c011c489fefe13fcce0ce4af140",
      "normalized_sha256": "c4a12ce5c6daacff312fff6605a053a7d4380e566bab0792544a55c8540c8a57"
    },
    "prospects/universal.py": {
      "git_blob": "87ec1137f6c4b9ceb406bad34f795e6e7c58474d",
      "normalized_sha256": "e76faa90af633f84fcc54bc4b45678d4a9bdc1ae273bc20ad01a5000b151da57"
    },
    "prospects/universe.py": {
      "git_blob": "7502ced75ce9ba174d7628bc93ceb0d344554968",
      "normalized_sha256": "dffe794fa21c9dfc20e1db78947434d8b0c5e2b5a802c053902538255e30a2b6"
    },
    "scripts/audit_consensus_decisions.py": {
      "git_blob": "d133e22bd6e0eeabf06bef45dcaf41837a1d239a",
      "normalized_sha256": "26ade2ae2b6b15e90db816a043b4621f12393d594f3df87190bf05914fd02829"
    },
    "scripts/build_ahead_of_consensus_scorecard.py": {
      "git_blob": "71f1125e47ce27ac5baf0ec73457cac9e6b8898d",
      "normalized_sha256": "d9ac9d55b2a363a3148b1da02ddc3cd6dba146629ff5baab57286b41f36e26b8"
    },
    "scripts/build_prospect_v23_candidate.py": {
      "git_blob": "2dd1aa18a43e94f268abc1778ef6c1cbf74e9646",
      "normalized_sha256": "318ab42ec65e42bb9b9e4799cca0531da7cf13e9123907a65f55a6e79830a69f"
    }
  },
  "folds": {
    "order": [
      2018,
      2019,
      2021
    ],
    "training_by_test": {
      "2018": [
        2019,
        2021
      ],
      "2019": [
        2018,
        2021
      ],
      "2021": [
        2018,
        2019
      ]
    },
    "identity_hash_formula": "canonical_sha256(sorted([[int(mlbam_id),str(role)]...]))",
    "identity_receipts": {
      "2018": {
        "hitter": {
          "count": 345,
          "sha256": "6169bf1c3de6430b74e1d3b425aac491bfcbd364a13afe12abcbc8b2b7c838d0"
        },
        "pitcher": {
          "count": 352,
          "sha256": "d5214fdfc761a84dc21702aa76aee7c302ea635c9d722235f1de3b5631dd5b76"
        }
      },
      "2019": {
        "hitter": {
          "count": 360,
          "sha256": "fccc74b819ff48c03402e0d8b791a18bef43a67470b749dd26de3f651b7d059a"
        },
        "pitcher": {
          "count": 410,
          "sha256": "e49cf8d1b6419bb7b1ce989223f51ae5a96178ef10f2616a42d41ce411462958"
        }
      },
      "2021": {
        "hitter": {
          "count": 386,
          "sha256": "f0b4610897c4d5564259aa06c19c394b03a7f72d11e992028588eb4b6efbf21d"
        },
        "pitcher": {
          "count": 365,
          "sha256": "55f9a77380bcf8159b32dd54b7b17c1fbd3bff9a9e59e57c994060b3c85ccd27"
        }
      }
    },
    "same_held_out_identities_and_targets": [
      "candidate",
      "control",
      "product"
    ]
  },
  "comparators": {
    "candidate": {
      "ladders": {
        "hitter": "v1",
        "pitcher": "v0_9"
      },
      "map": "independent_five_parameter_fold_fit",
      "standardization": "own_training_role_means_and_standard_deviations",
      "order": "unrounded_candidate_board_order"
    },
    "control": {
      "ladders": {
        "hitter": "v1",
        "pitcher": "v1"
      },
      "map": "independent_five_parameter_fold_fit",
      "standardization": "own_training_role_means_and_standard_deviations",
      "order": "unrounded_control_board_order"
    },
    "product": {
      "source": "reconstructed_v1_product_logic",
      "score": "emitted_two_decimal_score",
      "rank": "original_emitted_rank",
      "order": [
        "score_desc",
        "score_source_order",
        "role",
        "name",
        "numeric_mlbam_id"
      ],
      "rank_reproduction": "exact_1_through_n",
      "concordance_input": "emitted_score",
      "top25_input": "original_ranks_1_through_25",
      "mae": "forbidden_undefined"
    },
    "held_out_target_dependency": false
  },
  "metrics": {
    "rules": [
      {
        "name": "candidate_control_mae_delta",
        "expression": "candidate_mae-control_mae",
        "operator": "<",
        "threshold": 0
      },
      {
        "name": "candidate_control_concordance_delta",
        "expression": "candidate_concordance-control_concordance",
        "operator": ">",
        "threshold": 0
      },
      {
        "name": "candidate_concordance_above_chance",
        "expression": "candidate_concordance",
        "operator": ">",
        "threshold": 0.5
      },
      {
        "name": "candidate_product_concordance_delta",
        "expression": "candidate_concordance-product_concordance",
        "operator": ">",
        "threshold": 0
      },
      {
        "name": "candidate_control_top25_target_sum",
        "expression": "candidate_top25_target_sum-control_top25_target_sum",
        "operator": ">=",
        "threshold": 0
      },
      {
        "name": "candidate_product_top25_target_sum",
        "expression": "candidate_top25_target_sum-product_top25_target_sum",
        "operator": ">=",
        "threshold": 0
      }
    ],
    "mae": "arithmetic_mean(abs(expected_tier-target))_over_exact_held_out_universe",
    "cross_role_concordance": {
      "pairs": "hitter_pitcher_with_unequal_targets_only",
      "agreement": 1,
      "reverse": 0,
      "exact_score_tie": 0.5,
      "equal_targets": "excluded",
      "no_eligible_pairs": "undefined"
    },
    "top25": {
      "minimum_universe_rows": 25,
      "candidate_control": "first_25_in_unrounded_registered_order",
      "product": "emitted_ranks_1_through_25",
      "value": "sum_same_registered_targets"
    },
    "fold_policy": "every_fold_passes_no_pooled_or_majority_rescue",
    "fail_closed_checks": [
      "finite_values",
      "probabilities",
      "positive_slopes",
      "role_order",
      "identity",
      "target",
      "leakage",
      "forbidden_inputs"
    ]
  },
  "bootstrap": {
    "rng": "numpy.random.default_rng",
    "seed": 39017,
    "replicates": 10000,
    "minimum_valid_replicates": 9900,
    "fold_order": [
      2018,
      2019,
      2021
    ],
    "role_order": [
      "hitter",
      "pitcher"
    ],
    "identity_input_order": "ascending_numeric_mlbam_id",
    "sampling": "paired_replacement_within_each_fold_and_role",
    "sample_plan": "one_shared_plan_for_all_metrics_and_comparators",
    "map_refit": false,
    "fold_aggregation": "equal_weight_three_fold_deltas",
    "interval": {
      "method": "linear",
      "percentiles": [
        2.5,
        97.5
      ]
    },
    "pooled_rules": [
      {
        "name": "candidate_control_mae_delta",
        "bound": "upper",
        "operator": "<",
        "threshold": 0
      },
      {
        "name": "candidate_control_concordance_delta",
        "bound": "lower",
        "operator": ">",
        "threshold": 0
      },
      {
        "name": "candidate_product_concordance_delta",
        "bound": "lower",
        "operator": ">",
        "threshold": 0
      }
    ],
    "seed_hygiene": {
      "token": 39017,
      "standalone_pattern": "(^|[^0-9])39017([^0-9]|$)",
      "approved_design_commit": "1737468b16717ee6f7d24ea08b8444fdde3442f2",
      "pre_design_tip": "e48360faddab5504638324f70cddae25f7b7bc65",
      "pre_design": {
        "scan_domain": "all_raw_git_object_payloads_reachable_from_tip",
        "object_count": 25751,
        "sorted_object_ids_sha256": "c79396f3122f6053d1c35701807078c68545783545966827168ee289da551767",
        "match_count": 0,
        "scan_contract": "git_rev_list_cat_file_batch_rg_bytes_v1"
      },
      "post_design": {
        "scope_tip": "e1229bacc1c64d651609a5e621de0ec528a79a78",
        "inventory_schema": "git_blob_path_offset_v1",
        "entry_count": 128,
        "inventory_sha256": "d69eaa17701b66172796b66a7943373e00ad3924f1e2168702d506c5c76b5ef5",
        "allowed_paths": [
          "docs/superpowers/specs/2026-08-20-prospect-rank-vnext-current-board-design.md",
          "docs/superpowers/plans/2026-08-20-prospect-rank-vnext-phase-a.md",
          "scripts/build_prospect_v23_candidate.py",
          "tests/test_prospect_v23_development.py",
          "tests/fixtures/prospect_v23_registration_static_preimage.json"
        ],
        "unexpected_path_count": 0
      },
      "structured_seed_fields": {
        "inventory_sha256": "d7e6be460ac197fa5c29b0f8539dbb28eee72eddc4fa6744b0b6df6d410b456d",
        "pre_design_match_count": 0,
        "forbidden_held_spent_reserved_membership": false
      },
      "post_registration_policy": {
        "allowed_paths": [
          "plans/038-prospect-vnext-phase-a.md",
          "data/validation/valucast_prospect_rank_v2_3_registration.json",
          "data/validation/valucast_prospect_rank_v2_3_development.json",
          "tests/test_prospect_v23_development.py"
        ],
        "verify_current_head": true
      }
    }
  },
  "state_machine": {
    "lock_file": "valucast-prospect-v23.lock",
    "spent_token": "valucast-prospect-v23-spent.json",
    "states": [
      "reserved",
      "outcome_access_spent",
      "qualified",
      "failed",
      "spent_error"
    ],
    "cli": [
      "",
      "--resume-reserved",
      "--seal-interrupted-spend",
      "--reproduce"
    ],
    "exit_codes": {
      "qualified": 0,
      "failed": 1,
      "spent_error": 2
    }
  },
  "outputs": {
    "receipt": "data/validation/valucast_prospect_rank_v2_3_development.json",
    "calibrator": "data/models/valucast_prospect_joint_ladder_calibrator_v5.json"
  },
  "forbidden_inputs": [
    "2022_outcomes_or_confirmation",
    "current_public_rank_or_value",
    "consensus_rank",
    "market_rank_or_value",
    "governor_result",
    "player_name",
    "role_quota"
  ],
  "forbidden_paths": [
    "prospects/current_rank.py",
    "data/models/valucast_prospect_rank_v1.json",
    "data/prediction_archive/valucast_prospect_rank_v1/**",
    "data/validation/valucast_prospect_2022_confirmation_manifest.json",
    "data/models/valucast_model_registry.json",
    "data/public/public_dynasty_snapshot.json",
    "data/models/valucast_quality_governor.json",
    "scripts/build_public_dynasty_snapshot.py",
    "scripts/build_valucast_quality_governor.py",
    ".github/workflows/daily-public-data.yml",
    "app.py",
    "templates/**",
    "static/**"
  ],
  "feeds_live_rank": false,
  "feeds_value": false,
  "runtime": {
    "compiler": "MSC v.1944 64 bit (AMD64)",
    "implementation": "CPython",
    "machine": "AMD64",
    "numpy": "1.26.4",
    "platform": "Windows-11-10.0.26200-SP0",
    "python": [
      3,
      14,
      3
    ],
    "releaselevel": "final",
    "scipy": "1.17.1",
    "serial": 0
  },
  "execution": {
    "approved_sha_environment": "VALUCAST_V23_APPROVED_EXECUTION_SHA",
    "lock_scope": "repository_common_directory",
    "lock_acquisition": "nonblocking_lifetime_lock",
    "normal": "lifetime_lock_and_lowercase_40hex_environment_equals_head",
    "resume": "lifetime_lock_and_environment_equals_head_and_reserved_receipt_execution_sha",
    "recovery": "lifetime_lock_and_environment_equals_head_and_immutable_token_and_receipt_execution_sha_no_outcome_open",
    "reproduction": "lifetime_lock_and_terminal_receipt_execution_sha_no_knobs_no_writes",
    "spend_order": [
      "durable_immutable_token",
      "receipt_outcome_access_spent",
      "first_outcome_open"
    ],
    "pre_marker_error": "resumable_only_with_all_bindings_unchanged",
    "post_marker_error": "terminal_spent_error",
    "terminal_states": [
      "qualified",
      "failed",
      "spent_error"
    ],
    "map_only_when": "qualified",
    "invalid_unlisted_cli_or_exit": true,
    "application_data_read_allowlist": {
      "pre_spend": [
        "data/validation/valucast_prospect_rank_v2_3_registration.json"
      ],
      "post_spend": [
        "data/validation/valucast_prospect_v2_development_contract.json",
        "data/models/valucast_prospect_model_v0_9.json",
        "data/validation/valucast_prospect_rank_v2_1_development.json",
        "data/validation/valucast_prospect_rank_v2_2_development.json"
      ],
      "reproduce_additional": {
        "receipt": "data/validation/valucast_prospect_rank_v2_3_development.json",
        "calibrator": "data/models/valucast_prospect_joint_ladder_calibrator_v5.json",
        "calibrator_condition": "qualification_only"
      }
    }
  },
  "artifact_sha256": "6d1b0fe42887b4dff3f4b37bc0774c789b349ab38eab869233eebbc0f2217aec"
}
```
<!-- prospect-vnext-phase-a-registration:end -->

## Terminal transition

None. The registration is unspent and no execution is authorized. A later
terminal-evidence commit may append the observed terminal status, receipt hash,
and execution SHA here without editing the registered contract.
