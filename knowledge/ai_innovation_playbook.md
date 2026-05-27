---
id: ai_innovation_playbook
version: 0.1
status: active
last_reviewed: 2026-05-27
purpose: one_time_innovation_calibration
---

# AI Innovation Playbook

## Purpose

This is a calibration asset for AI-to-Fin gap generation. It is not a catalog
of AI topics and it is not a list of automatically approved financial research
directions. Its role is to teach the generator how strong AI papers turn an
observed failure into a new control point and a discriminating experiment.

Use it in two ways:

- `grounded_transfer`: an innovation pattern improves an existing active
  finance transfer cell. This can proceed to a full engineering proposal.
- `frontier_extension`: an innovation pattern exposes a concrete finance
  failure mode not represented by any active cell. This remains a theoretical
  proposal until a human approves a new cell.

For either mode, the AI paper is evidence for an intervention, not a brand
name to paste into finance.

## Innovation Test

A credible transfer should answer all six questions:

1. What assumption in the prior AI workflow failed?
2. What observable failure exposed that assumption?
3. What new control point does the AI paper insert?
4. Is there an operationally equivalent failure in a maintained finance field?
5. What intermediate prediction distinguishes the mechanism from ordinary
   model improvement?
6. What result would refute the transfer?

A `frontier_extension` must additionally explain why no current transfer cell
can express its failure mode or experiment anchor.

## Runtime Prompt Digest

For each recent AI mechanism, test this chain before proposing finance work:
`broken prior assumption -> observable AI failure -> new control point ->
operationally homologous finance failure -> falsifiable experiment`.

Reusable patterns:

- Process verification: check intermediate execution errors, not only final
  performance.
- Strategic monitoring: detect shortcut or audit-evasion behavior under an
  explicit evaluation rule.
- Interaction-driven tool mastery: learn reliable tool actions from execution
  failures, not documentation alone.
- Stateful adaptation: update bounded, time-valid memory for evolving state.
- Asynchronous evaluation: test actions while external state changes.
- Causal feature intervention: intervene on interpretable internal state, not
  just correlate attribution with outcomes.
- Workflow/search allocation: adapt verify/retrieve/backtest budget under a
  fixed cost envelope.
- Explicit uncertainty decisions: map scenarios and loss to actions instead of
  trusting fluent point recommendations.

Use `grounded_transfer` when an active cell already expresses the financial
failure and experiment. Use `frontier_extension` only when a specific new
failure/control point cannot be expressed by existing cells; provide the
missing failure, intervention, minimal experiment anchor, and why it is not a
renamed existing cell. Reject topic matches and brand-name transfers.

## Patterns

### 1. Process Verification Instead Of Outcome-Only Selection

**Broken assumption**: selecting outputs by final success is sufficient even
when failures originate inside a long reasoning or action trajectory.

**Control point**: introduce a process verifier that labels intermediate
steps, tool calls, or state transitions and feeds that signal into search,
repair, or policy improvement.

**Evidence design in AI**: compare outcome-only selection with process-level
feedback while measuring error localization and final performance.

**Finance translation questions**:

- Does an apparently profitable factor, portfolio, or agent trace contain an
  earlier invalid action that final PnL cannot identify?
- Can point-in-time violations, invalid formulas, unsupported claims, or
  constraint breaches be verified at the step where they arise?
- Does process feedback reduce invalid discoveries at a matched search budget?

**Invalid transfer warning**: a second LLM that merely reranks final returns
is not process verification unless it checks identifiable intermediate errors.

**Representative evidence**:

- [Rewarding Progress: Scaling Automated Process Verifiers for LLM Reasoning,
  ICLR 2025 Spotlight](https://openreview.net/forum?id=A6Y7AqlzLW): replaces
  sparse outcome feedback with automated step-level process rewards.
- [Generative Universal Verifier as Multimodal Meta-Reasoner, ICLR 2026
  Oral](https://openreview.net/forum?id=DM0Y0oL33T): inserts verification and
  refinement over generated outcomes rather than trusting first-pass output.

### 2. Dynamic Monitoring Against Strategic Or Hidden Failure

**Broken assumption**: a static evaluator remains reliable once an acting
agent adapts to or exploits its evaluation rule.

**Control point**: monitor behavior under adversarial conditions and test
whether apparently good outcomes are achieved with implausibly low effort or
through an unobserved shortcut.

**Evidence design in AI**: vary monitor awareness, adversarial strategy, and
environment; test failure detection rather than average task accuracy only.

**Finance translation questions**:

- Could a financial research agent optimize reported metrics while hiding
  leakage, cherry-picking, or policy-violating actions?
- Could a strategy pass a backtest through an easier shortcut than the claimed
  economic mechanism?
- What audit signal distinguishes genuine research progress from reward
  hacking?

**Invalid transfer warning**: generic robustness testing is not monitoring of
strategic failure unless the failure agent can exploit an explicit evaluation
or governance loophole.

**Representative evidence**:

- [Reliable Weak-to-Strong Monitoring of LLM Agents, ICLR 2026
  Oral](https://openreview.net/forum?id=WV7xIboTDK): stress-tests monitors
  against covert agent behavior and adversarial evasion.
- [Is it Thinking or Cheating? Detecting Implicit Reward Hacking by Measuring
  Reasoning Effort, ICLR 2026 Oral](https://openreview.net/forum?id=Gk7gLAtVDO):
  tests whether high reward arose from a shortcut rather than intended work.

### 3. Tool Mastery Through Interaction, Not Static Documentation

**Broken assumption**: supplying API documentation is enough for reliable
tool selection and parameterized execution in unfamiliar environments.

**Control point**: let an agent interact with tools, observe failures, and
construct operational knowledge from execution traces.

**Evidence design in AI**: hold tools or environments out and test adaptation
and successful execution, rather than evaluating descriptive tool knowledge.

**Finance translation questions**:

- Do financial agents fail because they cannot map semantic intent to specific
  database, filing, pricing, or risk APIs?
- Can execution-driven tool learning lower wrong-source, wrong-date, and
  invalid-parameter failures in real workflows?
- Is success measurable as correct trace execution rather than fluent answers?

**Invalid transfer warning**: giving an LLM more finance tool descriptions is
not an innovation unless an interaction-derived control loop changes errors.

**Representative evidence**:

- [From Exploration to Mastery: Enabling LLMs to Master Tools via Self-Driven
  Interactions, ICLR 2025 Oral](https://openreview.net/forum?id=QKBu1BOAwd):
  targets inadequate human-centric tool documentation through interactions.
- [In-the-Flow Agentic System Optimization for Effective Planning and Tool Use,
  ICLR 2026 Oral](https://openreview.net/forum?id=Mf5AleTUVK): trains modular
  agent behavior in the dynamics of multi-turn tool interaction.

### 4. Stateful Adaptation Under Non-Stationarity

**Broken assumption**: a fixed context window or a fixed policy remains
adequate when the relevant state evolves over long histories or new
environments.

**Control point**: retrieve analogous experience or maintain an updated,
compressed memory that changes decisions as new state arrives.

**Evidence design in AI**: evaluate held-out environments, long-context
extrapolation, or evolving state; compare with static-context baselines.

**Finance translation questions**:

- Which financial decisions depend on an evolving state that cannot be
  represented by a fixed recent window: regime shifts, covenant histories,
  analyst revisions, or prior tool failures?
- Can memory updates improve decisions without leaking future information?
- Does the memory retain decision-relevant state rather than simply expanding
  prompt length?

**Invalid transfer warning**: storing arbitrary past text is not stateful
adaptation; the experiment must test update rules and time-valid information.

**Representative evidence**:

- [REGENT: A Retrieval-Augmented Generalist Agent That Can Act In-Context in
  New Environments, ICLR 2025 Oral](https://openreview.net/forum?id=NxyfSW6mLK):
  uses retrieval as an adaptation bias in unseen environments.
- [MemAgent: Reshaping Long-Context LLM with Multi-Conv RL-based Memory Agent,
  ICLR 2026 Oral](https://openreview.net/forum?id=k5nIOvYGCL): learns segment
  processing and memory overwrite policies for long contexts.

### 5. Dynamic And Asynchronous Evaluation

**Broken assumption**: performance measured in static, synchronous tasks
represents reliability in environments that change independently of actions.

**Control point**: construct asynchronous environments and action-level
verifiers so temporal validity and adaptation become measurable.

**Evidence design in AI**: change the environment while the agent acts and
score write actions under temporal constraints and ambiguity.

**Finance translation questions**:

- Are existing financial-agent evaluations static snapshots while filings,
  prices, news, limits, or position constraints evolve during a workflow?
- Can a benchmark inject timestamped events or stale evidence to test temporal
  validity and re-planning?
- What actions should be rejected when the underlying state has changed?

**Invalid transfer warning**: adding newer test dates is not asynchronous
evaluation unless decisions must react to state changes during execution.

**Representative evidence**:

- [Gaia2: Benchmarking LLM Agents on Dynamic and Asynchronous Environments,
  ICLR 2026 Oral](https://openreview.net/forum?id=9gw03JpKK4): pairs changing
  environments with action-level verification.
- [Speculative Actions: A Lossless Framework for Faster AI Agents, ICLR 2026
  Oral](https://openreview.net/forum?id=P0GOk5wslg): exposes sequential action
  latency as a first-class agent-system constraint.

### 6. Intervention Through Interpretable Causal Features

**Broken assumption**: predictive performance or attention inspection is
enough to understand and control the internal mechanism producing behavior.

**Control point**: discover sparse interpretable features and causal circuits,
then edit or monitor those features to test whether behavior changes for the
claimed reason.

**Evidence design in AI**: measure feature faithfulness and perform controlled
edits or interventions, rather than relying on descriptive visualizations.

**Finance translation questions**:

- In a deep factor or risk model, can an interpretable latent state reveal
  reliance on fragile proxies, crowding signals, or regime-specific shortcuts?
- Can intervening on that state change exposure or decay diagnostics while
  preserving legitimate predictive structure?
- Is the claimed mechanism causal or only correlated with returns?

**Invalid transfer warning**: feature attribution alone is not causal
diagnosis; a finance proposal must include intervention or out-of-regime tests.

**Representative evidence**:

- [Scaling and evaluating sparse autoencoders, ICLR 2025
  Oral](https://openreview.net/forum?id=tcsZt9ZNKD): scales sparse feature
  extraction and evaluates recovered representations.
- [Sparse Feature Circuits: Discovering and Editing Interpretable Causal
  Graphs in Language Models, ICLR 2025 Oral](https://openreview.net/forum?id=I4e82CIDxv):
  moves from feature description to causal circuit editing.
- [Temporal Sparse Autoencoders: Leveraging the Sequential Nature of Language
  for Interpretability, ICLR 2026 Oral](https://openreview.net/forum?id=bojVI4l9Kn):
  adds temporal structure where local features lose evolving semantics.

### 7. Search And Self-Improvement Over Reasoning Procedures

**Broken assumption**: one manually designed reasoning workflow, or more model
parameters alone, is the appropriate way to improve difficult decisions.

**Control point**: search over workflows, generate self-supervised reasoning
experience, or allocate test-time compute adaptively to difficult cases.

**Evidence design in AI**: compare procedures or inference budgets on held-out
tasks and measure improvement under matched computation.

**Finance translation questions**:

- Does a financial research pipeline have multiple expensive stages whose
  allocation should depend on uncertainty, novelty, or audit risk?
- Can workflow search find when to retrieve, verify, backtest, or stop rather
  than simply produce more candidate ideas?
- Can improvements be shown at a fixed data, API, and backtest budget?

**Invalid transfer warning**: unconstrained extra LLM calls are not a research
mechanism; a proposal needs a budget-matched policy and stopping rule.

**Representative evidence**:

- [AFlow: Automating Agentic Workflow Generation, ICLR 2025
  Oral](https://openreview.net/forum?id=z5uVAKwmjf): treats agent workflow
  design as an optimization object.
- [ReGenesis: LLMs can Grow into Reasoning Generalists via Self-Improvement,
  ICLR 2025 Oral](https://openreview.net/forum?id=YUYJsHOf3c): examines
  self-synthesized reasoning trajectories beyond supervised expert traces.
- [Scaling LLM Test-Time Compute Optimally Can be More Effective than Scaling
  Parameters for Reasoning, ICLR 2025 Oral](https://openreview.net/forum?id=4FWAwZtd2n):
  formalizes inference-time allocation under compute budgets.

### 8. Decision Support That Represents Uncertainty Explicitly

**Broken assumption**: a plausible single recommendation is adequate when
decisions depend on uncertain states and asymmetric losses.

**Control point**: represent scenarios, probabilities, or utilities before
selecting actions, allowing decisions to reflect uncertainty rather than
surface confidence.

**Evidence design in AI**: vary uncertainty and decision complexity; compare
direct prompting with an explicit decision representation.

**Finance translation questions**:

- Do portfolio, allocation, risk, or analyst-agent decisions conflate forecast
  accuracy with the utility of an action?
- Can scenario-conditioned choices improve calibration, constraint compliance,
  or tail-risk behavior without claiming superior return prediction?
- Which uncertainties are measurable ex ante and which are invented by the
  model?

**Invalid transfer warning**: generic requests for confidence intervals do not
constitute uncertainty-aware decision support without a choice rule or loss.

**Representative evidence**:

- [DeLLMa: Decision Making Under Uncertainty with Large Language Models, ICLR
  2025 Spotlight](https://openreview.net/forum?id=Acvo2RGSCy): introduces
  structured assistance for increasingly complex uncertain decisions.
- [Reasoning Elicitation in Language Models via Counterfactual Feedback, ICLR
  2025 Oral](https://openreview.net/forum?id=VVixJ9QavY): uses
  counterfactual-sensitive evaluation rather than factual accuracy alone.

## Frontier Extension Rules

Use `frontier_extension` only when all of these hold:

- A recent AI paper instantiates one of the above patterns through a concrete
  intervention and evaluation.
- A selected finance field contains an operationally equivalent failure or a
  defensible new failure adjacent to its maintained boundary.
- No active transfer cell captures the new control point and experiment.
- The proposal states a new failure mode, intervention class, and minimal
  experiment anchor: data object, primary metric, baseline, and falsifier.
- It is clearly marked as requiring human review before it modifies the
  maintained taxonomy or produces a deep engineering brief.

Reject a frontier extension when it is only a topic match, requires unavailable
future information, omits a refutable prediction, or merely renames an
existing active cell.
