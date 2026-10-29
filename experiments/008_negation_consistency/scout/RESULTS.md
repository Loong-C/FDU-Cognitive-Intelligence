# V8 scout

Historical development exploration

Complete: True; new calls: {'negative': 6}; new tokens: {'negative': 2815}.

| Dataset | Method | Correct/n | Accuracy | Macro F1 | S recall | R recall | NEI recall |
|---|---|---|---|---|---|---|---|
| challenge | baseline | 14/21 | 66.67% | 0.6084 | 100.00% | 100.00% | 30.00% |
| challenge | nli | 17/21 | 80.95% | 0.7037 | 100.00% | 50.00% | 70.00% |
| challenge | signed_consensus | 17/21 | 80.95% | 0.7037 | 100.00% | 50.00% | 70.00% |
| basic | baseline | 21/21 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |
| basic | nli | 20/21 | 95.24% | 0.9475 | 100.00% | 83.33% | 100.00% |
| basic | signed_consensus | 21/21 | 100.00% | 1.0000 | 100.00% | 100.00% | 100.00% |

No test data was accessed. Missing/invalid final predictions count as errors. No-significant-loss does not establish noninferiority.
Full class/ mechanism/ group metrics, paired changes and group uncertainty are in metrics.json.
