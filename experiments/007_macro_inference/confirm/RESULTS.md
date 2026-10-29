# V7 confirm

Purpose: new group-separated development validation. Complete: True.
Baseline: contemporaneous_same_batch. Missing/invalid predictions count as errors.

| Dataset | Method | Correct/n | Accuracy | Macro F1 | S recall | R recall | NEI recall |
|---|---|---|---|---|---|---|---|
| basic | baseline | 56/60 | 93.33% | 0.9332 | 94.74% | 94.44% | 91.30% |
| basic | nli | 60/60 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |
| challenge | baseline | 26/41 | 63.41% | 0.6276 | 100.00% | 100.00% | 31.82% |
| challenge | nli | 30/41 | 73.17% | 0.7034 | 92.86% | 80.00% | 59.09% |

## Gates

```json
{
  "nli": {
    "dataset_and_class_dominance": false,
    "also_every_mechanism": false
  }
}
```

Per-mechanism, per-group, paired changes, bootstrap intervals and costs are in metrics.json.
Exploratory comparisons are not independent test evidence. Test data was not read.
