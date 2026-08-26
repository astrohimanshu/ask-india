# Decisions and roads not taken

Each entry: what was decided, why, and what it cost.

**Grounding is enforced by code, not prompts.** The composer is told to use only the rows, but
the guarantee comes from a numeral extractor that checks every figure in the prose against the
result rows (and the question, SQL and citation, which are provenance rather than memory). One
regeneration, then refusal. Cost: prose that mentions a derived figure the query did not return
is refused even when the arithmetic is right; the fix is to put the arithmetic in the SQL.

**SQL safety is two independent layers.** `sqlglot` admits exactly one `SELECT` over the `data`
and `rag` schemas with a forbidden-function list and an enforced `LIMIT`; the database role the
agent uses can only `SELECT`, runs read-only transactions and times out at 10 s. Either layer
alone would be a single point of failure.

**Verdicts are arithmetic.** The model extracts the claimed figure and the question that settles
it; the comparison uses documented bands (±10 % Supported, same direction within a factor of two
Misleading, otherwise Contradicted). The model never decides the verdict. Cost: claims that need
judgement ("roughly doubled") get a mechanical answer, which is the point.

**Triage fails closed, then a deterministic check fails it closed again.** After the model names
the dataset that can settle a claim, the years the claim mentions are compared with that
dataset's coverage span; anything outside is Unverifiable before a query runs. This came out of
the L2 run, where a claim about 2019 airport traffic was confidently contradicted by a dataset
that starts in 2023.

**A small local model in development, and the same family in production.** Development uses
`qwen2.5-coder:7b` and `qwen2.5:7b-instruct` on the shared GPU through Ollama, routed by
LiteLLM so the production model is one environment variable away. Azure OpenAI was not available
on this subscription, so production runs a CPU Ollama container with `qwen2.5-coder:3b`; its
accuracy is measured separately and disclosed rather than assumed to match.

**Six datasets fetched from the publishers, not from data.gov.in.** `api.data.gov.in` timed out
or rate-limited from both build machines, so every dataset comes from the ministry's own site.
Two planned sources were dropped rather than approximated: CPI (press-release PDFs only) and
MoRTH road accidents (discovery did not complete). The spike report that made the call is
committed.

**Loaders fail loud.** A batch that fails validation is quarantined with its report and never
partially loaded; the previous version stays queryable. Odisha's rainfall page publishes 2023
twice with different values, so 2023 is absent for Odisha rather than guessed.

**Result equivalence, not SQL text, in evaluation.** Two different queries can both be right, and
an extra column is not a wrong answer. Rows are compared as multisets with numeric tolerance for
rounding.

**A self-hosted runner for the merge gate.** A hosted runner cannot run the 7B model, and a gate
measured on a different model would not measure the product. Jobs from forks never reach the
runner.

**Container Apps over AKS; kind for the Kubernetes credential.** Scale-to-zero fits a $100
credit; the manifests are exercised on a local kind cluster instead of paid nodes. The
subscription allows one Container Apps environment in total, so the apps live in their own
resource group but reuse the existing environment by id.

**No OIDC from CI to Azure.** The tenant blocks app registrations, so no cloud credential exists
in GitHub; CI publishes images to GHCR and the rollout is a scripted `az` step from an operator
machine.

**pgvector instead of a vector database; Postgres instead of Redis.** One stateful service holds
data, embeddings and application state at this scale; a swap is a small change if scale demands.

**Secrets never reach the CI log.** The self-hosted runner reads the development `.env` from the
host, but sourcing it into `$GITHUB_ENV` made every later step print the values in a public
Actions log. Jobs now source the file inside the step that needs it, so the values stay in that
process. The incident is recorded here rather than quietly fixed: the affected run logs were
deleted and the exposed database passwords rotated.
