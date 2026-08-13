# Incomplete Prospect History and Scoreboard Label Implementation Plan

1. Add model selector regressions for incomplete and complete historical rows; verify RED.
2. Add the minimum shared selector guard so incomplete history cannot override a newer current-season line while history-only players remain unchanged; verify GREEN.
3. Update the scoreboard view/template regressions to distinguish cohorts from boards; verify RED.
4. Correct the derived label and explanatory copy in `app.py` and `templates/forward_scoreboard.html`; verify GREEN.
5. Run focused and broader affected suites, inspect the diff, and report any resulting board movement before publication.
