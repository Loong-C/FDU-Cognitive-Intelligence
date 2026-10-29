# V8 confirm

New group-separated development confirmation

Complete: True; new calls: {'baseline': 101, 'positive': 101, 'negative': 14}; new tokens: {'baseline': 37531, 'positive': 39888, 'negative': 8248}.

| Dataset | Method | Correct/n | Accuracy | Macro F1 | S recall | R recall | NEI recall |
|---|---|---|---|---|---|---|---|
| basic | baseline | 60/60 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |
| basic | nli | 56/60 | 93.33% | 0.9318 | 92.31% | 95.65% | 91.67% |
| basic | signed_consensus | 59/60 | 98.33% | 0.9858 | 100.00% | 100.00% | 95.83% |
| challenge | baseline | 26/41 | 63.41% | 0.6341 | 85.71% | 100.00% | 40.91% |
| challenge | nli | 34/41 | 82.93% | 0.7997 | 100.00% | 100.00% | 68.18% |
| challenge | signed_consensus | 31/41 | 75.61% | 0.7353 | 100.00% | 100.00% | 54.55% |

No test data was accessed. Missing/invalid final predictions count as errors. No-significant-loss does not establish noninferiority.
Full class/ mechanism/ group metrics, paired changes and group uncertainty are in metrics.json.
