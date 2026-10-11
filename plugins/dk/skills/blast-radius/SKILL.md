---
name: blast-radius
description: "Find what a change could break beyond its diff, and prove the one fact it is safe because of by running real code. Use for 'blast radius of X', 'what could this break', a one-way-door PR, a diff you don't trust, or before a parallel wave of tickets touches shared modules."
---

<!-- Adapted from cursor/plugins pstack@d73344b skills/blast-radius, MIT (© 2026 Lauren Tan). Changed for dk-agent-kit: model-invoked, pointers to how/why/arena/unslop replaced. -->

# Blast radius

Find what a change breaks somewhere else, before it ships. Listing the callers is not the job; grep does that in a second. The job is the breakage grep won't show you.

## Proof over prose

A blast-radius writeup that sounds right is worthless: it reads as convincing whether or not it is true. Find the one or two facts the whole change depends on and prove them by running code.

For each fact the change's safety depends on, get it as far down this ladder as is cheap, and say where it stopped:

1. You said so. Worthless on its own.
2. You pointed at the line: a real `file:line`, or the library's own source.
3. You showed the bad case can't happen: you walked the failure step by step and it doesn't reach.
4. You ran it: a script or test that calls the real code and fails loud if you're wrong.
5. You reproduced it in the running app.

Step 4 is usually one small script that imports the same library the app ships and calls the exact function you're worried about.

## Steps

1. **Read the change.** The diff, the symbols it adds, changes and deletes, and what it now does differently, including what the diff doesn't spell out. `git log -p`, the PR (`gh pr view N --json title,body,commits`) and its issue give the intent.
2. **Find the one fact it is safe because of.** Most risky-looking changes are safe because of a single fact, like "this call only drops already-dead cache entries". If it holds, most risky cases clear at once. Spend your time here, not on a long list of maybes.
3. **Look where grep stops.** Read the source of the library you call at its pinned version, and any local patch. Work out when things run: goroutines, transactions, microtasks, unmount and teardown, WebSocket reconnects. Follow what a symbol search misses: the JSON an API returns, a DB column or migration, a wire format, the other app reading the same endpoint, a feature flag, a cached value, code three hops downstream.
4. **Weigh each risk honestly.** Give it a real chance of happening and a real cost if it does. Keep the risks you confirmed; list the ones you checked and cleared separately. Cite a real `file:line`; a search that finds nothing is still an answer.
5. **Prove the one fact.** Write a script or test that runs the real code, run it, and paste what happened.

## Shared modules before a parallel wave

When several tickets will run in parallel, list the files and modules each one is likely to touch and flag every module two or more tickets share. For each shared module, recommend one of: serialize those tickets with a blocking edge, give one ticket ownership and the others a dependency on it, or split the module first as a prefactor ticket.

## Hand back

- **What it does**: what changed, including the part that isn't obvious.
- **The one fact it's safe because of**: stated, the ladder step reached, and the proof, or **unproven**.
- **Risks**: how each breaks, `file:line`, likelihood and cost, and how to check. Paste the proof for the ones that matter.
- **Cleared**: what you checked and why it's fine.
- **Before you merge**: the cheapest test or repro that catches the real bug, including the script you wrote.
