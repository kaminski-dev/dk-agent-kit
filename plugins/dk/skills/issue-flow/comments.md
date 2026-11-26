# Comments

For any session about to post a comment or thread reply, on a PR or an issue, or to correct one it posted (`dk:issue-flow` step 6).

**Comments.** You post under the maintainer's gh account, so every comment and thread reply you post, on a PR or an issue, in step 6 and step 7, opens with this attribution note, then a blank line, then the reply:

```md
> [!NOTE]
> **<model> responding on behalf of <login>**
```

`<model>` is the public model name the harness reports, such as `Claude Opus 5.5`, or the harness's own name when it reports none; `<login>` is `gh api user --jq .login`. This is the note's one definition: a script that skips your own comments matches a body against the Python `re` pattern `\A> \[!NOTE\]\r?\n> \*\*.+ responding on behalf of .+\*\*`. The PR body, commit messages and text the maintainer asks you to post verbatim carry no note, nor does anything on a repo step 1's **Ownership.** finds is not your own. Post the body from a file, and keep the URL GitHub answers with: `gh pr comment <PR> --body-file "<file>"` and `gh issue comment N --body-file "<file>"` print it, and a thread reply gives it with `gh api "repos/{owner}/{repo}/pulls/<PR>/comments/<id>/replies" -F "body=@<file>" --jq .html_url`. Resolve a review thread only once its reply posted and GitHub returned the reply's URL. To correct a comment you posted, write the whole new body, note included, to a file and run `dk-comment-edit <comment id> <file>`, the id from the comment's URL: it edits only your own comment that opens with the attribution note, needs no approval, and prints the URL.
