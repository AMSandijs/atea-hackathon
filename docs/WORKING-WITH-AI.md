# Working with AI in this repo

The single most useful thing to understand: **the AI will agree with you if you let it.**
Ask "is this a good idea?" and you will get a yes with three supporting bullet points,
regardless of the idea. Everything below is about not doing that.

---

## The four questions

Every idea we take into the weekend has to survive these. They are not a formality —
they are what killed two of our earlier ideas and reshaped the two that survived.

**1. Is the AI load-bearing, or is this a for-loop with an LLM bolted on?**
If a plain script does the job, the AI is decoration and a judge will say so in thirty
seconds. The test: remove the model entirely. What breaks? If the answer is "nothing
important", find the part of the workflow that involves a *judgement*, and build that
instead.

**2. Why must it be local — and does the answer survive one follow-up?**
"Privacy" is not an answer, it's a slogan. A real answer names what specifically cannot
leave the machine and who says so. The strongest form is when local isn't a preference
but a definition — for example, the thing that decides what's safe to send obviously
cannot itself be a cloud service.

**3. Can you show it in 90 seconds?**
Something has to visibly happen. Value that consists of what *didn't* go wrong is real
but very hard to demo, and needs measurements to compensate.

**4. Is there a real person with this problem, and a number?**
"Someone probably does this" loses to "Deivids does this eight times a day." One named
person with a real frequency beats any amount of market reasoning.

---

## Two modes, two ways of prompting

### Thinking mode — working on an idea

Do this in `ideas/`. Copy `_TEMPLATE.md`, fill it in roughly, then attack it.

**The pressure-test prompt.** Paste your one-pager, then this:

> This is an idea for a local-AI hackathon. Before you tell me anything good about it,
> answer these:
>
> 1. What's the strongest reason this fails? Not a risk — the reason.
> 2. Is the AI load-bearing here, or is this a script with a model bolted on? Be blunt.
> 3. "Why does this have to run locally" — give me the answer, then attack it the way a
>    sceptical engineer would in Q&A.
> 4. How many other teams at a local-AI hackathon will pitch roughly this same idea?
> 5. What's the demo, beat by beat, in 90 seconds? If you can't, say so.
>
> Then, and only then, tell me what's genuinely strong about it and what you'd change.

The order matters. Asking for problems *after* asking for strengths gets you hedged
problems.

**Follow-ups that work:**

- *"You're being agreeable. What would someone who thinks this is a waste of a weekend
  say?"*
- *"What's the version of this idea that's 20% of the work and 80% of the value?"*
- *"Who already sells this? Why isn't their thing good enough?"*
- *"If we built this and it failed on stage, what would have failed?"*

**Things to be sceptical of in the reply:** confident claims about what a specific
product does today (Copilot, Purview, Basware — verify against docs, these move),
invented API signatures, and any latency or accuracy number it didn't measure.

### Building mode — implementing a project

Under `projects/<name>/`. The pattern:

1. *"Read AGENTS.md and docs/ARCHITECTURE.md in this project."*
2. *"Do the lowest-numbered unfinished task in docs/BUILD-PLAN.md. Just that one. Stop
   and report when its acceptance criteria pass."*
3. Read what it did. Run the tests yourself. Then ask for the next one.

**Do not let it chain tasks.** An agent that does T4 through T8 in one go produces a lot
of plausible code that nobody has looked at, and you find out on Saturday night.

**When it goes off the rails,** the usual causes:

- *It invented its own module names.* The architecture doc specifies them. Point at the
  doc and ask it to conform, or to amend the doc first if something's genuinely missing.
- *It wrote code with no tests.* A task isn't done without them; say so.
- *It hallucinated a library API.* Ask it to check the installed version's actual
  signature before using it. `pip show` and reading the source is faster than arguing.
- *It quietly changed approach.* If it couldn't do the task as written it should have
  said so. Ask what it changed and why.

---

## Splitting work across three people

The build plans are ordered, which makes parallel work awkward early and easy later.
Rough shape:

- **T1-T2 together**, or one person while the other two do prep from the *Before the 25th*
  checklist. Nothing parallelises before the skeleton exists.
- **After that**, the module map in `ARCHITECTURE.md` shows the seams. Two people on
  different modules with agreed data shapes will not collide.
- **One person owns the demo and the deck from Saturday evening.** Not as an afterthought
  on Sunday night — it's a third of the score.

## One more thing

If you find yourself arguing with the AI about whether your idea is good, you've already
learned something. The useful move at that point is to write down the strongest version
of its objection in your one-pager under *Known weaknesses*, and see whether you still
want to build it. Usually you do, and now you have the answer ready for Monday.
