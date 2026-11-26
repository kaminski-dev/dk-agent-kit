# Guard shapes no past command hits

A guard issue asks `dk-guard` to ask, deny or allow a command shape. `/dk:triage` admits one as `ready-for-agent` only with a past command that hit the shape (its **Guard issues** section). The shapes below had none when they were triaged, so their issues were closed as `wontfix` and parked here.

## Why this is out of scope

A guard rule is paid for on every Bash call and in every later fix: one guard issue took 13 commits, four review rounds and 81 findings, while its own replay over 84,159 past calls changed no verdict. 13 of 16 guard issues in the 2026-11 retro window descended from another fix, and the guard grew from 927 to 1,829 lines. A shape that no past command reached costs that much and protects nothing yet.

The shapes stay recorded so a new issue that names one finds its earlier search. When a past command hits a shape, reopen its issue, take its entry out and triage it again with that command as the guard's failing case.

## Shapes

Each entry: the shape with an example command, the issue, and the search that found no hit (its command, date and the number of calls it covered).

None yet.
