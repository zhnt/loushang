# Issue 798: raw measurement samples, 2026-10-20

Authority: informative — local measurement evidence.

See [interpretation and limitations](issue-798-performance-evidence-2026-10-20.md).

## Installed CLI

```json
{
  "baseline": "installed baseline wheel",
  "baseline_commit": "2de1359c31d540913df11a7f4705f5a1b54624ba",
  "baseline_idle_median_s": 7.0293,
  "candidate": "installed candidate wheel",
  "candidate_commit": "ea64899df6b1ad94c0313a9eb8e01a2f4a2166e5",
  "candidate_idle_median_s": 4.3112,
  "child_cpu_median_s": {
    "baseline": 7.2863,
    "candidate": 4.7812
  },
  "dependency_control": "same 34 dependency versions in both installed-wheel environments",
  "idle_improvement_percent": 38.67,
  "idle_spread_ratio": {
    "baseline": 1.515,
    "candidate": 1.368
  },
  "measurement": "installed_cli_pty_welcome_and_idle",
  "os_cache": "not controlled; alternating order only",
  "p90_s": {
    "baseline": {
      "child_cpu_s": 7.7066,
      "idle_s": 7.3953,
      "welcome_s": 2.0255
    },
    "candidate": {
      "child_cpu_s": 5.13,
      "idle_s": 5.0338,
      "welcome_s": 1.0894
    }
  },
  "platform": "macOS x86_64",
  "priming": "one unrecorded fresh-private-home startup per build before the paired samples",
  "python_version": "3.14.7",
  "rounds": 11,
  "samples": {
    "baseline": [
      {
        "child_cpu_s": 7.0497,
        "exit_code": 0,
        "idle_s": 7.3311,
        "welcome_s": 1.974
      },
      {
        "child_cpu_s": 8.4834,
        "exit_code": 0,
        "idle_s": 8.7524,
        "welcome_s": 2.3564
      },
      {
        "child_cpu_s": 7.7066,
        "exit_code": 0,
        "idle_s": 7.134,
        "welcome_s": 1.7683
      },
      {
        "child_cpu_s": 7.4074,
        "exit_code": 0,
        "idle_s": 7.0293,
        "welcome_s": 1.6117
      },
      {
        "child_cpu_s": 7.2395,
        "exit_code": 0,
        "idle_s": 6.7423,
        "welcome_s": 1.4643
      },
      {
        "child_cpu_s": 7.2863,
        "exit_code": 0,
        "idle_s": 6.7721,
        "welcome_s": 1.4907
      },
      {
        "child_cpu_s": 7.0659,
        "exit_code": 0,
        "idle_s": 6.5305,
        "welcome_s": 1.609
      },
      {
        "child_cpu_s": 6.3297,
        "exit_code": 0,
        "idle_s": 5.7758,
        "welcome_s": 1.3849
      },
      {
        "child_cpu_s": 6.6412,
        "exit_code": 0,
        "idle_s": 6.1172,
        "welcome_s": 1.3761
      },
      {
        "child_cpu_s": 7.5127,
        "exit_code": 0,
        "idle_s": 7.3953,
        "welcome_s": 1.4387
      },
      {
        "child_cpu_s": 7.5584,
        "exit_code": 0,
        "idle_s": 7.1334,
        "welcome_s": 2.0255
      }
    ],
    "candidate": [
      {
        "child_cpu_s": 4.9919,
        "exit_code": 0,
        "idle_s": 4.9605,
        "welcome_s": 1.0577
      },
      {
        "child_cpu_s": 4.82,
        "exit_code": 0,
        "idle_s": 4.3309,
        "welcome_s": 0.8658
      },
      {
        "child_cpu_s": 5.13,
        "exit_code": 0,
        "idle_s": 5.0338,
        "welcome_s": 1.1402
      },
      {
        "child_cpu_s": 4.7812,
        "exit_code": 0,
        "idle_s": 4.3112,
        "welcome_s": 0.8541
      },
      {
        "child_cpu_s": 4.7559,
        "exit_code": 0,
        "idle_s": 4.4617,
        "welcome_s": 1.0894
      },
      {
        "child_cpu_s": 4.7308,
        "exit_code": 0,
        "idle_s": 4.2919,
        "welcome_s": 0.9243
      },
      {
        "child_cpu_s": 4.8241,
        "exit_code": 0,
        "idle_s": 4.2544,
        "welcome_s": 0.8282
      },
      {
        "child_cpu_s": 4.4069,
        "exit_code": 0,
        "idle_s": 4.0989,
        "welcome_s": 0.8072
      },
      {
        "child_cpu_s": 4.6725,
        "exit_code": 0,
        "idle_s": 4.3026,
        "welcome_s": 0.8331
      },
      {
        "child_cpu_s": 4.4822,
        "exit_code": 0,
        "idle_s": 3.932,
        "welcome_s": 0.8326
      },
      {
        "child_cpu_s": 5.4101,
        "exit_code": 0,
        "idle_s": 5.3778,
        "welcome_s": 1.0834
      }
    ]
  },
  "schema_version": 2,
  "scope": "fresh private home and cwd; no model request or LSP use",
  "timing_warning": "idle times vary by more than 20% within a build; do not attribute the difference",
  "welcome_median_s": {
    "baseline": 1.609,
    "candidate": 0.8658
  }
}
```

## First LSP result

```json
{
  "baseline_commit": "2de1359c31d540913df11a7f4705f5a1b54624ba",
  "candidate_commit": "ea64899df6b1ad94c0313a9eb8e01a2f4a2166e5",
  "dependency_control": "same 34 dependency versions in both installed-wheel environments",
  "platform": "macOS x86_64",
  "python_version": "3.14.7",
  "samples": {
    "baseline": [
      {
        "activation_and_first_result_s": 0.13914,
        "activation_s": 0.000922,
        "import_s": 7.87634,
        "ready_and_first_result_s": 8.452123,
        "second_result_s": 0.007958,
        "session_ready_s": 8.312983
      },
      {
        "activation_and_first_result_s": 0.134196,
        "activation_s": 0.000751,
        "import_s": 8.767962,
        "ready_and_first_result_s": 8.318101,
        "second_result_s": 0.008035,
        "session_ready_s": 8.183905
      },
      {
        "activation_and_first_result_s": 0.135399,
        "activation_s": 0.00077,
        "import_s": 6.650444,
        "ready_and_first_result_s": 8.603118,
        "second_result_s": 0.007908,
        "session_ready_s": 8.467718
      },
      {
        "activation_and_first_result_s": 0.116898,
        "activation_s": 0.000794,
        "import_s": 6.604595,
        "ready_and_first_result_s": 5.296687,
        "second_result_s": 0.007519,
        "session_ready_s": 5.179789
      },
      {
        "activation_and_first_result_s": 0.142206,
        "activation_s": 0.000809,
        "import_s": 4.171497,
        "ready_and_first_result_s": 6.456921,
        "second_result_s": 0.009266,
        "session_ready_s": 6.314715
      }
    ],
    "candidate": [
      {
        "activation_and_first_result_s": 4.857791,
        "activation_s": 4.687952,
        "import_s": 7.169208,
        "ready_and_first_result_s": 5.83592,
        "second_result_s": 0.008778,
        "session_ready_s": 0.978129
      },
      {
        "activation_and_first_result_s": 5.434612,
        "activation_s": 5.280117,
        "import_s": 8.971486,
        "ready_and_first_result_s": 6.56662,
        "second_result_s": 0.007022,
        "session_ready_s": 1.132008
      },
      {
        "activation_and_first_result_s": 3.931917,
        "activation_s": 3.786512,
        "import_s": 6.732104,
        "ready_and_first_result_s": 4.825126,
        "second_result_s": 0.008919,
        "session_ready_s": 0.893209
      },
      {
        "activation_and_first_result_s": 4.029201,
        "activation_s": 3.898949,
        "import_s": 6.492472,
        "ready_and_first_result_s": 4.793752,
        "second_result_s": 0.009282,
        "session_ready_s": 0.764551
      },
      {
        "activation_and_first_result_s": 3.287495,
        "activation_s": 3.158791,
        "import_s": 6.307579,
        "ready_and_first_result_s": 4.031632,
        "second_result_s": 0.008603,
        "session_ready_s": 0.744137
      }
    ]
  },
  "scope": "installed macOS legacy SDK route; module import separate; private state; no model call; real local fake LSP process"
}
```

## Output pressure

```json
{
  "baseline_commit": "2de1359c31d540913df11a7f4705f5a1b54624ba",
  "candidate_commit": "ea64899df6b1ad94c0313a9eb8e01a2f4a2166e5",
  "dependency_control": "same 34 dependency versions in both installed-wheel environments",
  "platform": "macOS x86_64",
  "python_version": "3.14.7",
  "samples": {
    "baseline": [
      {
        "all_updates_sha256": "a93eac6a9b863853b3c261cfa469a395868704654453689a060e4108b5df5312",
        "append_s": 9.376331,
        "bytes": 2048000,
        "chunks": 2000
      },
      {
        "all_updates_sha256": "a93eac6a9b863853b3c261cfa469a395868704654453689a060e4108b5df5312",
        "append_s": 9.873941,
        "bytes": 2048000,
        "chunks": 2000
      },
      {
        "all_updates_sha256": "a93eac6a9b863853b3c261cfa469a395868704654453689a060e4108b5df5312",
        "append_s": 9.483295,
        "bytes": 2048000,
        "chunks": 2000
      }
    ],
    "candidate": [
      {
        "all_updates_sha256": "a93eac6a9b863853b3c261cfa469a395868704654453689a060e4108b5df5312",
        "append_s": 2.396344,
        "bytes": 2048000,
        "chunks": 2000
      },
      {
        "all_updates_sha256": "a93eac6a9b863853b3c261cfa469a395868704654453689a060e4108b5df5312",
        "append_s": 2.751787,
        "bytes": 2048000,
        "chunks": 2000
      },
      {
        "all_updates_sha256": "a93eac6a9b863853b3c261cfa469a395868704654453689a060e4108b5df5312",
        "append_s": 2.536643,
        "bytes": 2048000,
        "chunks": 2000
      }
    ]
  },
  "scope": "2000 interleaved stdout/stderr chunks, 2048000 bytes; append work timed; serialization excluded; digest covers content and every metadata field on every update"
}
```
