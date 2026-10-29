# V7 scout

Purpose: historical exploratory development. Complete: True.
Baseline: historical_v4_not_contemporaneous. Missing/invalid predictions count as errors.

| Dataset | Method | Correct/n | Accuracy | Macro F1 | S recall | R recall | NEI recall |
|---|---|---|---|---|---|---|---|
| challenge | baseline | 14/21 | 66.67% | 0.6084 | 100.00% | 100.00% | 30.00% |
| challenge | nli | 17/21 | 80.95% | 0.7037 | 100.00% | 50.00% | 70.00% |
| challenge | certificate | 14/21 | 66.67% | 0.6084 | 100.00% | 100.00% | 30.00% |
| challenge | dual | 17/21 | 80.95% | 0.7037 | 100.00% | 50.00% | 70.00% |
| challenge | consensus_nli_certificate | 14/21 | 66.67% | 0.6084 | 100.00% | 100.00% | 30.00% |
| challenge | consensus_nli_dual | 16/21 | 76.19% | 0.6639 | 100.00% | 50.00% | 60.00% |
| challenge | consensus_certificate_dual | 14/21 | 66.67% | 0.6084 | 100.00% | 100.00% | 30.00% |
| basic | baseline | 21/21 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |
| basic | nli | 20/21 | 95.24% | 0.9475 | 100.00% | 83.33% | 100.00% |
| basic | certificate | 21/21 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |
| basic | dual | 19/21 | 90.48% | 0.9070 | 100.00% | 83.33% | 85.71% |
| basic | consensus_nli_certificate | 21/21 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |
| basic | consensus_nli_dual | 21/21 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |
| basic | consensus_certificate_dual | 21/21 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |

## Gates

```json
{
  "nli": {
    "dataset_and_class_dominance": false,
    "also_every_mechanism": false
  },
  "certificate": {
    "dataset_and_class_dominance": false,
    "also_every_mechanism": false
  },
  "dual": {
    "dataset_and_class_dominance": false,
    "also_every_mechanism": false
  },
  "consensus_nli_certificate": {
    "dataset_and_class_dominance": false,
    "also_every_mechanism": false
  },
  "consensus_nli_dual": {
    "dataset_and_class_dominance": false,
    "also_every_mechanism": false
  },
  "consensus_certificate_dual": {
    "dataset_and_class_dominance": false,
    "also_every_mechanism": false
  }
}
```

Per-mechanism, per-group, paired changes, bootstrap intervals and costs are in metrics.json.
Exploratory comparisons are not independent test evidence. Test data was not read.
