"""Operation-effect projection (DCE-G1R3B) — additive, opt-in, read-only.

G1R3A's ``effect_view`` gives every objective exactly **one** effect class. That is not safe for operations whose single verb has
several effects: *deploying* executes something **and** changes the environment; *running an arbitrary script* executes something
and may do anything else. A prohibition on one class ("do not change the production cluster") must therefore block an operation
whose **set of potential effects** contains that class ("deploy to production"), even though its primary class differs.

This module projects each objective onto an :class:`OperationEffect` with

* ``primary_operation`` — the class the verb itself denotes;
* ``potential_effects`` — the full set of classes the operation could cause, from an explicit, auditable **operator registry**
  (:data:`OPERATOR_REGISTRY`) plus effects the text itself attributes to the operation ("a script that writes results to
  output.json");
* ``unknown_external_effects`` / ``effect_completeness`` — ``True``/``"unknown"`` when the operation runs something whose behaviour
  the text does not establish (an arbitrary script, command, job, pipeline …) and no trusted **tool declaration** scopes it;
* ``effect_evidence`` — ``{source_id, source_span, reason}`` provenance for every class in the set;
* conditions / approval flags from the structural graph.

:func:`operation_policy` is the operation-level counterpart of ``effect_view.effect_policy``: it intersects the union of potential
and tool-declared effects with the text's prohibitions and returns ``DENY`` / ``REQUIRE_RESOLUTION`` / ``TEXT_NOT_PROHIBITED`` —
never ``ALLOW``. Unknown effects require resolution; unknown effects **under any prohibition** are denied; a conflict on **any**
possible effect denies the whole operation.

Nothing here executes, schedules, or authorizes anything. ``project_effects`` / ``effect_policy`` are untouched and remain
available; their single-class limit is documented in ``docs/system/F2B-001.md``.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from .schema import ACTION_CLASS, Objective, RequestIR, Span, Unresolved
from .rules import ACTION_RULES
from . import policy_view as pv
from . import effect_view as ev
from .effect_view import (
    ARTIFACT_WRITE, COMMAND_EXECUTION, DENY, ENVIRONMENT_MUTATION, REPLY_ONLY, REQUIRE_RESOLUTION, SIDE_EFFECT_CLASSES,
    TEXT_NOT_PROHIBITED, UNKNOWN, EffectProjection, ProhibitedEffect, project_effects,
)

__all__ = ["OperationEffect", "OperationProjection", "ToolDeclaration", "OperationEvidence", "OPERATOR_REGISTRY",
           "project_operations", "operation_policy", "OPERATION_PROJECTION_VERSION"]

OPERATION_PROJECTION_VERSION = "dce-g1r3d/0.4.0"

_I = re.I | re.U
_W = r"(?<![\w'’-])"


# --- operator registry -------------------------------------------------------------------------------------------------
# key → (primary class, potential classes, unknown_external_effects, trigger regex, object regex or None)
# A registry row matches an objective when its *trigger* (the verb the parser found) or, for generic run/execute verbs, its
# *object* matches. Rows are tried in order; the first match wins. This table is the whole of the "what can this verb do"
# knowledge — change it here, never in ad-hoc string exceptions.

@dataclass(frozen=True)
class _Operator:
    name: str
    primary: str
    potential: tuple[str, ...]
    unknown_external: bool
    trigger: Optional[re.Pattern]
    obj: Optional[re.Pattern]
    actions: tuple[str, ...]        # parser actions the row applies to


def _rx(p: str) -> re.Pattern:
    return re.compile(_W + p, _I)


_ARTICLE_RE = re.compile(r"^\s*(?:(?:the|a|an|this|that|our|my|your|another|a new|the new|цей|цю|це|той|ту|наш|нашу|наше|новий|нову|нове)\s+)+", _I)
_LIGHT_VERB_RE = _rx(r"(?:make|do|perform|carry out|зроби(?:ти)?|зробіть|проведи(?:ти)?|проведіть|виконай(?:те)?)\b")   # "make a release" / "зроби реліз"
_GENERIC_RUN_RE = _rx(r"(?:run|execute|exec|launch|kick off|trigger|invoke|fire|запусти(?:ти)?|запустіть|виконай(?:те)?|виконати|запуск\w*|викона\w*)\b")

OPERATOR_REGISTRY: tuple[_Operator, ...] = (
    _Operator("deploy", COMMAND_EXECUTION, (COMMAND_EXECUTION, ENVIRONMENT_MUTATION), False,
              _rx(r"(?:deploy\w*|redeploy\w*|release\w*|roll(?:[- ]?out|s? out|ed out|ing out)|roll(?:[- ]?back|s? back|ed back|ing back)|promot\w+|revert\w*|"
                  r"розгорн\w*|задепло\w*|деплой\w*|викот\w*|відкот\w*|реліз\w*|промоут\w*)"), None, ("run", "modify", "create")),
    _Operator("service_control", COMMAND_EXECUTION, (COMMAND_EXECUTION, ENVIRONMENT_MUTATION), False,
              _rx(r"(?:restart\w*|reboot\w*|start\w*|stop\w*|scale\w*|kill\w*|drain\w*|cordon\w*|failover|fail over|pause|resume|flush\w*|purg\w*|evict\w*|invalidat\w*|"
                  r"перезапус\w*|перезаванта\w*|зупин\w*|запусти(?:ти)? сервіс|масштаб\w*|вимкн\w*|увімкн\w*)"), None, ("run",)),
    _Operator("apply_change", COMMAND_EXECUTION, (COMMAND_EXECUTION, ENVIRONMENT_MUTATION), False,
              _rx(r"(?:migrat\w*|apply\w*|appl(?:y|ied|ies|ying)|install\w*|upgrade\w*|reinstall\w*|patch\w*|provision\w*|rotat\w*|terraform apply|kubectl apply|"
                  r"мігр\w*|накат\w*|накот\w*|застос\w*|встанов\w*|інстал\w*|онов\w* (?:пакет|залежност|версі)|ротац\w*|перевипус\w*)"), None, ("run",)),
    _Operator("verify_run", COMMAND_EXECUTION, (COMMAND_EXECUTION,), False, None,
              _rx(r"(?:(?:unit |integration |smoke |e2e |regression |acceptance |snapshot |contract |property |mutation |golden |visual |api |ui |the |all |our |full |complete |entire |whole |relevant |existing |new |affected |failing |"
                  r"існуюч\w+ |повн\w+ |усі |всі |юніт[- ]?|інтеграційн\w+ )*(?:tests?|test suite|suite)(?!\s+(?:scripts?|jobs?|commands?|programs?|pipelines?|runners?|harness(?:es)?|wrappers?)\b)|smoke suite|"
                  r"pytest|jest|vitest|mocha|tox|nox|go test|cargo test|npm test|yarn test|make test|"
                  r"linter|lint|flake8|ruff|mypy|pylint|eslint|prettier|black|formatter|type[- ]?check\w*|build|compile\w*|benchmark\w*|dry[- ]?run|plan|"
                  r"тест\w*|лінтер\w*|лінт\w*|збірк\w*|білд\w*|бенчмарк\w*|перевірк\w* тип\w*)\b"
                  # "the benchmark script that writes …", "a build job", "the lint tool" — an arbitrary runner behind the noun: behaviour not established (sheet v5 rule 25)
                  r"(?!\s+(?:scripts?|jobs?|tools?|commands?|programs?|pipelines?|runners?|harness(?:es)?|wrappers?|binar(?:y|ies)|utilit(?:y|ies))\b)"), ("run",)),
    _Operator("service_publish", ENVIRONMENT_MUTATION, (ENVIRONMENT_MUTATION,), False,
              _rx(r"(?:publish\w*|post\w*|send\w*|e-?mail\w*|upload\w*|push\w*|force[- ]?push\w*|merge\w*|rebas\w*|cherry[- ]?pick\w*|squash\w*|amend\w*|tag\w*|commit(?:s|ted|ting)?\b|перебаз\w*|ребейз\w*|черіпік\w*|notify|announce\w*|share\w*|submit\w*|file|raise|"
                  r"опублік\w*|надішл\w*|надісла\w*|відправ\w*|відішл\w*|запость|запост\w*|залий|залити|завантаж\w*|запуш\w*|змерж\w*|злий|злити|"
                  r"повідом\w*|анонс\w*|подай|подати|заведи|завести)"), None, ("run", "create", "modify")),
    _Operator("arbitrary_execution", COMMAND_EXECUTION, (COMMAND_EXECUTION,), True, _GENERIC_RUN_RE,
              _rx(r"(?:scripts?|commands?|programs?|binar(?:y|ies)|jobs?|pipelines?|playbooks?|notebooks?|workflows?|cron\w*|tasks?|make\b|makefile|"
                  r"shell|bash|sh\b|python|node|npm|npx|yarn|pip|docker|kubectl|ansible|terraform|helm|curl|wget|ssh|rsync|"
                  r"скрипт\w*|команд\w*|програм\w*|джоб\w*|пайплайн\w*|плейбук\w*|ноутбук\w*|воркфлоу|крон\w*|задач\w*|"
                  r"[\w./-]+\.(?:sh|py|bash|ps1|rb|js|ts|pl|bat|cmd|exe|jar)\b|`[^`]+`|\./[\w./-]+|[\w-]+\.(?:sh|py)\b)"), ("run",)),
)

_GIT_REF_TOKEN_RE = re.compile(r"(?<![\w.])(?:feature|feat|hotfix|bugfix|fix|release|releases|chore|refactor|exp|experiment|spike|wip|dev|rel|user|users|v?\d+\.\d+(?:\.\d+)?)/[\w./-]+", _I)
_FILE_TAIL_RE = re.compile(r"\.(?:md|py|yaml|yml|json|txt|sh|rst|html?|csv|toml|ini|cfg|conf|sql|js|ts|tsx|jsx|xml|env|lock|log|tf|hcl|adoc|pdf|docx?|xlsx?|png|svg)$|/$", _I)


class _GitRef:
    """``search(text)`` → a match-like object for a Git ref such as ``hotfix/queue-timeout`` (a ``prefix/segment`` token without a file
    extension); ``docs/runbook.md`` and ``src/api.py`` are files, not refs."""

    @staticmethod
    def search(text: str):
        for m in _GIT_REF_TOKEN_RE.finditer(text):
            if not _FILE_TAIL_RE.search(m.group(0).rstrip(".,;:")):
                return m
        return None


_GIT_REF_RE = _GitRef()
_GIT_NOUN_RE = _rx(r"(?:branch\w*|tags?|pull requests?|merge requests?|PRs?|MRs?|commits?|forks?|releases?(?![-\w]| (?:notes?|checklist|plan|summary|report|doc\w*|announcement|email|message))|гілк\w*|тег\w*|пул[- ]?реквест\w*|мердж[- ]?реквест\w*|пр\b|мр\b|коміт\w*|реліз\w*)\b")
_TICKET_NOUN_RE = _rx(r"(?:tickets?|issues?|incidents?|jira|linear|github issue|epics?|stor(?:y|ies)|tasks? in (?:jira|linear|asana|trello)|(?:confluence|notion|wiki) pages?|pages? (?:in|on) (?:confluence|notion|the wiki)|"
                      r"(?:support|service|vendor|customer) cases?|cases? (?:with|at|in) (?:support|the vendor|[\w-]+ support)|service requests?|change requests?|work items?|defect reports?|bug reports?|"
                      r"тікет\w*|тикет\w*|задач\w* (?:в|у) (?:jira|джир\w*|linear)|інцидент\w*|сторінк\w* (?:в|у|на) (?:confluence|notion|вікі)|епік\w*)\b")
_SERVICE_PLACE_RE = _rx(r"(?:jira|confluence|notion|slack|teams|github|gitlab|bitbucket|pagerduty|opsgenie|trello|asana|linear|sharepoint|wiki|channel|канал\w*|джир\w*|вікі)\b")
_CONFIG_OBJ_RE = _rx(r"(?:config\w*|settings?|setting|feature[- ]?flags?|flags?|firewall|iptables|dns|permissions?|roles?|quotas?|limits?|environment variables?|env vars?|secrets?|"
                     r"конфіг\w*|конфігурац\w*|налаштуванн\w*|прапорц\w*|фаєрвол\w*|дозвол\w*|квот\w*|ліміт\w*|змінн\w* середовищ\w*|секрет\w*)\b")
_FILE_HEAD_RE = re.compile(r"^\s*(?:(?:a|an|the|this|that|new|a new)\s+)?(?:(?:file|document|doc|note|page)\s+(?:called|named|at)\s+)?(?:`)?(?:[\w.-]+/)*[\w.-]+\.\w{1,6}\b", _I)
_SOURCE_FILE_RE = re.compile(r"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|kt|rb|php|c|h|cpp|cs|swift|scala|sql|sh|bash|md|rst|txt|html?|css|scss|csv|ipynb)\b", _I)
_CONFIG_FILE_RE = re.compile(r"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.(?:ya?ml|json|toml|ini|cfg|conf|env|tf|hcl|properties)\b|\.env\b|dockerfile|docker-compose", _I)
_WRITES_TO_RE = re.compile(r"(?:writes?|saves?|stores?|persists?|dumps?|exports?|appends?|outputs?|записує|зберігає|пише|експортує|вивантажує)\b[^.;]*?(?:to|into|in|у|в|до)\s+(?P<dst>[\w./-]+\.\w{1,6}|(?:a |the )?(?:files?|disk|файл\w*|диск)\b[\w./ -]*)", _I)
_WRITES_ARTEFACT_RE = re.compile(r"(?:updates?|updating|regenerates?|rewrites?|writes?|generates?|emits?|produces?|creates?|refreshes?|records?|overwrites?|"
                                 r"re-?creates?|re-?builds?|dumps?|exports?|materiali[sz]es?|renders?|bakes?|saves?|stores?|persists?|appends?|outputs?|publishes (?:to disk|files?))\b[^.;]*?"
                                 r"(?:\b(?:snapshots?|fixtures?|goldens?|golden files?|artifacts?|artefacts?|bundles?|files?|lock ?files?|reports?|coverage|baselines?|generated \w+|"
                                 r"clients?|stubs?|bindings?|typings?|types? files?|headers?|binaries|executables?|packages?|wheels?|jars?|images? to disk|docs?|documentation|site|static pages?|"
                                 r"build output|outputs?|logs? to disk|to disk|on disk|results? (?:files?|directory|folder)|cache files?)\b"
                                 # "… which rewrites __snapshots__/ui.snap", "that produces bench/results.json", "regenerates generated_schema.json" (sheet v5 rule 25)
                                 r"|(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.(?:snap|json|ya?ml|md|txt|csv|tsv|xlsx?|docx?|pptx?|parquet|xml|html?|lock|png|jpe?g|svg|pdf|log|sql|py|js|ts|toml|ini|cfg|out|bin|tar|gz|zip|db|sqlite|pkl|npz|h5)\b"
                                 r"|(?<![\w.])(?:\.?/)?[\w.-]+/[\w./-]*/?(?![\w.])"
                                 r"|--(?:update|write|fix|regenerate|record|snapshot-update|update-snapshots?|overwrite|save)\b)", _I)
_MUTATES_RE = re.compile(r"(?:drops?|deletes?|truncates?|alters?|modif(?:y|ies)|changes?|updates?|rewrites?|resets?|restarts?|deploys?|rotates?|migrates?|pushes|"
                         r"видаля\w*|змін\w*|онов\w*|скида\w*|перезапуска\w*|деплоїть|мігру\w*)\b[^.;]*?(?P<obj>\b(?:tables?|databases?|db|schemas?|clusters?|services?|pods?|nodes?|config\w*|settings?|secrets?|"
                         r"records?|rows?|users?|permissions?|production|prod|staging|таблиц\w*|баз\w*|кластер\w*|сервіс\w*|конфіг\w*|записи|продакшн\w*|прод\b)\b)", _I)
_PRONOUN_RE = ev._PRONOUN_OBJECT_RE
_BARE_PRONOUN_RE = re.compile(r"^\s*(?:it|them|this|that|these|those|one|його|її|їх|це|цей|ці|той|ті|них|ними)\s*(?:[.,;:!]|$|\s+(?:now|please|immediately|today|asap|зараз|негайно|сьогодні|будь ласка)\b)", _I)
_UNIVERSAL_OBJECT_RE = re.compile(r"^\s*(?:anything|everything|nothing|any (?:thing|of it|files? or settings?)|all of it|будь-що|все|усе|нічого|жодн\w+ (?:змін\w*|речей|файл\w*|налаштуван\w*))\b", _I)
_ALL_EFFECTS_PROHIBITED_RE = re.compile(r"(?:\b(?:no|zero|without any|not any)\s+(?:external|outside|real|actual|real-world|side)[- ]?(?:changes?|effects?|actions?|mutations?|modifications?|operations?)|"
                                        r"\b(?:do|perform|execute|make|take|carry out)\s+(?:nothing|no (?:actions?|operations?|steps?))(?:\s+(?:at all|whatsoever|else))?|\bnothing\s+(?:external|real|actual|at all)\b|\bread[- ]only\b|"
                                        # sheet v5 rule 23 (DCE-G1R3D): "do nothing outside / beyond chat", "no external / remote calls", "nothing should change", "chat only"
                                        r"\bnothing\s+(?:outside|beyond|except|other than|apart from|besides|but)\b|\b(?:no|zero)\s+(?:external|outside|remote|outbound|real|real-world)\s+(?:calls?|actions?|requests?|changes?|operations?|side[- ]effects?|effects?|writes?|interactions?|mutations?)\b|"
                                        r"\b(?:never|not|don't|do not)\s+(?:perform|take|make|execute|carry out|do)\s+(?:any\s+)?(?:external|outside|remote|real|real-world|side[- ]effecting|state[- ]changing)\s+(?:actions?|calls?|changes?|operations?|side[- ]effects?|requests?|effects?)\b|"
                                        r"\bnothing\s+(?:should|may|must|can|is to|shall|will)\s+(?:change|be changed|be modified|be touched|be altered|be written|be executed|happen|move|run)\b|"
                                        r"\b(?:stay|remain|keep(?: everything| it| this)?|work)\s+(?:strictly\s+)?(?:in|inside|within)\s+(?:the\s+|this\s+)?(?:chat|reply|answer|conversation)\b|\b(?:chat|text|answer|reply|conversation|discussion)[- ]only\b|"
                                        r"\b(?:жодних|ніяких|без (?:будь-яких|жодних))\s+(?:зовнішніх|реальних|фактичних|справжніх)\s+(?:змін|дій|ефектів|операцій)|"
                                        r"\bнічого\s+(?:не роби(?:ти)?|не виконуй(?:те)?|не змінюй(?:те)?|реального|зовнішнього)|\bне роби(?:ти)?\s+нічого|\bлише\s+читання|\bтільки\s+читання)", _I)
# a prohibited execute verb that the registry says also mutates the environment ("never deploy to production")
_MULTI_EFFECT_PROHIBITED_RE = _rx(r"(?:deploy\w*|redeploy\w*|release\w*|roll(?:[- ]?out|[- ]?back)|promot\w+|revert\w*|restart\w*|reboot\w*|stop\w*|scale\w*|kill\w*|"
                                  r"migrat\w*|apply\w*|install\w*|upgrade\w*|rotat\w*|розгорн\w*|задепло\w*|деплой\w*|викот\w*|відкот\w*|реліз\w*|перезапус\w*|"
                                  r"перезаванта\w*|зупин\w*|мігр\w*|застос\w*|встанов\w*|ротац\w*)")


# --- data ---------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class OperationEvidence:
    source_id: str                 # objective / constraint / unresolved id, or "tool:<name>"
    source_span: Optional[Span]
    reason: str                    # registry:<operator> | attributed:<class> | tool_declaration:<name> | destination | object | pronoun | …
    text: str = ""


@dataclass(frozen=True)
class ToolDeclaration:
    """A consumer-supplied statement of what a tool can do (never inferred from the text).

    DCE-G1R3C: a declaration can only **widen** an operation. ``pattern`` is matched against the operation's object text (and
    trigger); when it matches an execution-class operation, the declared ``effects`` are **unioned** with the registry / text
    effects, and ``unknown_external_effects`` is left exactly as the registry and text establish it. A loosely matched or
    unverified declaration can therefore never delete an inferred effect. Effect *narrowing* would require a separately
    validated, identity- and version-bound, scope-specific trusted tool contract — not implemented in this increment."""
    name: str
    pattern: str
    effects: tuple[str, ...]
    scope: str = ""

    def matches(self, text: str) -> bool:
        return re.search(self.pattern, text, _I) is not None


@dataclass(frozen=True)
class OperationEffect:
    objective_id: str
    action: Optional[str]
    operator: Optional[str]                    # registry row name or None
    primary_operation: str
    potential_effects: list[str]               # sorted, includes primary
    effect_completeness: str                   # "known" | "unknown"
    unknown_external_effects: bool
    effect_evidence: list[OperationEvidence]
    conditions: list[str]
    conditional: bool
    approval_required: bool
    constraint_ids: list[str]
    source_span: Span
    declared_tool: Optional[str] = None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OperationProjection:
    parser_version: str
    projection_version: str
    digest: str
    status: str
    operations: list[OperationEffect]
    prohibited_effects: list[ProhibitedEffect]
    unbound_restriction_ids: list[str]
    approval_gate_ids: list[str]
    side_effect_requested: bool                # any operation with a side-effect class in potential_effects (conditional counts)
    unknown_count: int                          # operations with primary unknown or effect_completeness unknown
    tool_declarations: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def operation(self, node_id: str) -> Optional[OperationEffect]:
        for op in self.operations:
            if op.objective_id == node_id:
                return op
        return None


# --- helpers -----------------------------------------------------------------------------------------------------------

def _evd(o_id: str, span: Optional[Span], reason: str, text: str = "") -> OperationEvidence:
    return OperationEvidence(o_id, span, reason, text)


def _span_of(m: Optional[re.Match], base: int) -> Optional[Span]:
    return Span(base + m.start(), base + m.end()) if m is not None else None


def _match_operator(o: Objective) -> Optional[tuple[_Operator, OperationEvidence]]:
    trig = o.trigger.text if o.trigger is not None else ""
    tbase = o.trigger.source_span.start if o.trigger is not None else o.source_span.start
    obj = o.target.text if o.target is not None else ""
    obase = o.target.source_span.start if o.target is not None else o.source_span.start
    for row in OPERATOR_REGISTRY:
        if o.action not in row.actions:
            continue
        if row.trigger is not None:
            m = row.trigger.search(trig)
            if m is not None and row.name != "arbitrary_execution":
                return row, _evd(o.id, _span_of(m, tbase), f"registry:{row.name}", m.group(0))
            if row.name != "arbitrary_execution" and obj and row.obj is None and ((o.action == "run" and _GENERIC_RUN_RE.search(trig)) or _LIGHT_VERB_RE.search(trig)):
                # "run a deploy", "execute the rollback", "виконай міграцію" — a generic run verb whose object *is* the operation
                m2 = row.trigger.match(_ARTICLE_RE.sub("", obj, count=1))
                if m2 is not None:
                    return row, _evd(o.id, o.target.source_span if o.target else None, f"registry:{row.name}", m2.group(0))
        if row.obj is not None and obj:
            # verify_run is anchored on the object head ("run the unit tests", not "run `make release` on the build host")
            m = row.obj.match(_ARTICLE_RE.sub("", obj, count=1)) if row.name == "verify_run" else row.obj.search(obj)
            if m is not None and row.name == "verify_run":
                m = row.obj.search(obj)
            if m is not None and (row.trigger is None or row.trigger.search(trig) or o.action == "run"):
                return row, _evd(o.id, _span_of(m, obase), f"registry:{row.name}", m.group(0))
    return None


def _antecedent_text(ir: RequestIR, o: Objective) -> Optional[str]:
    for r in o.references:
        if r.status != "unresolved" and r.resolved_to:
            for k in ir.graph.context_statements:
                if k.id == r.resolved_to:
                    return k.text
            for p in ir.graph.objectives:
                if p.id == r.resolved_to and p.target is not None:
                    return p.target.text
            for c in ir.graph.constraints:
                if c.id == r.resolved_to and c.target_object is not None:
                    return c.target_object.text
            return r.resolved_to                      # context referent text / protected-region id
    return None


def _registry_row_for_object(text: str) -> Optional[_Operator]:
    for row in OPERATOR_REGISTRY:
        if row.obj is not None and row.obj.search(text):
            return row
        if row.obj is None and row.trigger is not None and row.name != "service_publish" and row.trigger.search(text):
            return row
    return None


def _attributed_effects(o: Objective) -> list[tuple[str, OperationEvidence]]:
    """Effects the text itself attributes to an executed thing: "a script that writes results to output.json"."""
    obj = o.target.text if o.target is not None else ""
    base = o.target.source_span.start if o.target is not None else o.source_span.start
    out: list[tuple[str, OperationEvidence]] = []
    if not obj:
        return out
    m = _WRITES_TO_RE.search(obj)
    if m is not None:
        out.append((ARTIFACT_WRITE, _evd(o.id, _span_of(m, base), f"attributed:{ARTIFACT_WRITE}", m.group(0))))
    else:
        m = _WRITES_ARTEFACT_RE.search(obj)            # "tests that update the snapshots", "the build that generates the bundle"
        if m is not None:
            out.append((ARTIFACT_WRITE, _evd(o.id, _span_of(m, base), f"attributed:{ARTIFACT_WRITE}", m.group(0))))
    m = _MUTATES_RE.search(obj)
    if m is not None:
        out.append((ENVIRONMENT_MUTATION, _evd(o.id, _span_of(m, base), f"attributed:{ENVIRONMENT_MUTATION}", m.group(0))))
    trig = o.trigger.text if o.trigger is not None else ""
    if re.match(r"\s*(?:appl|patch|hot-?fix)", trig, _I) and not any(c == ARTIFACT_WRITE for c, _ in out):
        m = _APPLY_TO_FILE_RE.search(obj)              # "apply the fix to config/gateway.yaml" — the named file is written (DCE-G1R3D)
        if m is not None:
            out.append((ARTIFACT_WRITE, _evd(o.id, _span_of(m, base), f"attributed:{ARTIFACT_WRITE}", m.group(0))))
    return out


_APPLY_TO_FILE_RE = re.compile(r"\b(?:to|in|into|onto|against|inside|within)\s+(?:the\s+|this\s+|that\s+)?`?(?:[\w.-]+/)*[\w.-]+\.(?:ya?ml|json|toml|ini|cfg|conf|env|py|js|ts|tsx|jsx|go|rs|java|kt|rb|php|sh|md|txt|csv|xml|html?|css|sql|lock|properties)\b", _I)


_GENERIC_OBJ_RE = re.compile(r"^\s*(?:(?:the|a|an|this|that|these|those|my|our|your|its|all|any|some|pending|requested|proposed|necessary|needed|required)\s+)*"
                             # up to three modifier words: "the schema adjustment", "the performance correction", "the retry-policy tweak" (sheet v5 3.3a; DCE-G1R3D)
                             r"(?:(?!(?:to|in|on|into|at|for|from|of)\b)[\w'’-]+\s+){0,3}?"
                             r"(?:fix(?:es)?|hotfix(?:es)?|changes?|edits?|modifications?|updates?|adjustments?|tweaks?|amendments?|corrections?|improvements?|rework|workarounds?|alterations?)\b"
                             r"(?!\s*(?:log|set|request|history|list|management|control|window|freeze|review|ticket|summary|description|plan)\b)", _I)
_FILE_DEST_RE = re.compile(r"(?:" + ev._FILE_EXT_RE.pattern + r"|" + ev._PATH_RE.pattern + r"|" + ev._FILE_NOUN_RE.pattern + r")", _I)
_ENV_TARGET_RE = re.compile(r"\b(?:to|on|in|into|against)\s+(?:the\s+|our\s+|each\s+|every\s+|all\s+)?(?:(?:running|live|active|deployed|current|staging|production|prod|canary|primary|secondary|main)\s+)?"
                            r"(?:production|prod|staging|live|clusters?|servers?|hosts?|nodes?|fleet|environments?|env|gateway|gateways|proxy|proxies|load[- ]balancers?|"
                            r"services?|instances?|deployments?|pods?|containers?|database|db|databases)\b", _I)


def _generic_change_object(o: Objective) -> Optional[OperationEvidence]:
    """"make the change", "apply the fix", "prepare the changes" — the object is a generic change noun and names no file, path,
    configuration or environment: the medium is not established (sheet v4 rule 18 / 3.3a). None otherwise."""
    obj = o.target.text if o.target is not None else ""
    m = _GENERIC_OBJ_RE.match(obj)
    if m is None or _FILE_DEST_RE.search(obj) or _ENV_TARGET_RE.search(obj):   # "make the change in config.yaml", "apply the fix to production" are established
        return None
    base = o.target.source_span.start
    return _evd(o.id, _span_of(m, base), "ambiguous_medium", m.group(0).strip())


def _state_object(o: Objective) -> Optional[tuple[str, OperationEvidence]]:
    """create / modify / remove: is the object a Git ref, a ticket/page, a configuration, or a source file?"""
    obj = o.target.text if o.target is not None else ""
    base = o.target.source_span.start if o.target is not None else o.source_span.start
    if not obj:
        return None
    fm = _SOURCE_FILE_RE.search(obj)
    if fm is not None and o.action in ("create", "modify") and _CONFIG_FILE_RE.search(obj) is None and not ev._in_subject_phrase(obj, fm.start()) \
            and (_FILE_HEAD_RE.match(obj) or _GIT_REF_RE.search(obj) is None):
        return ARTIFACT_WRITE, _evd(o.id, _span_of(fm, base), "object:source_file", fm.group(0))   # "Create docs/operator-checklist.md with the release checklist"
    for rx, reason in ((_GIT_REF_RE, "git_ref"), (_GIT_NOUN_RE, "git_noun"), (_TICKET_NOUN_RE, "service_record"), (_SERVICE_PLACE_RE, "service_place")):
        m = rx.search(obj)
        if m is not None:
            return ENVIRONMENT_MUTATION, _evd(o.id, _span_of(m, base), f"object:{reason}", m.group(0))
    m = _CONFIG_FILE_RE.search(obj)
    if m is not None and not ev._in_subject_phrase(obj, m.start()):
        return ENVIRONMENT_MUTATION, _evd(o.id, _span_of(m, base), "object:config_file", m.group(0))
    m = _CONFIG_OBJ_RE.search(obj)
    if m is not None and o.action == "create" and not (_FILE_DEST_RE.search(obj) or _ENV_TARGET_RE.search(obj)):
        return None            # "prepare a config for the worker pool" — a new configuration with no stated place → medium unknown (sheet v4 3.3a; G1R3C)
    if m is not None and not (o.action == "create" and _GENERIC_OBJ_RE.match(obj) is None and ev._in_subject_phrase(obj, m.start())):
        return ENVIRONMENT_MUTATION, _evd(o.id, _span_of(m, base), "object:configuration", m.group(0))
    m = _SOURCE_FILE_RE.search(obj)
    if m is not None and o.action in ("create", "modify") and not ev._in_subject_phrase(obj, m.start()):   # "a patch for src/api.py" names the subject
        return ARTIFACT_WRITE, _evd(o.id, _span_of(m, base), "object:source_file", m.group(0))
    m = _ENV_TARGET_RE.search(obj)
    if m is not None and o.action == "modify" and _GENERIC_OBJ_RE.match(obj) is not None:   # "apply the change on the staging cluster" (DCE-G1R3D)
        return ENVIRONMENT_MUTATION, _evd(o.id, _span_of(m, base), "object:environment_target", m.group(0))
    return None


def _gates(ir: RequestIR, node_id: str) -> tuple[list[str], bool, bool]:
    conds = pv.conditions_for(ir, node_id)
    return [q.id for q in conds], bool(conds), any(ev._APPROVAL_RE.search(q.text) for q in conds)


def _base_intent(proj: EffectProjection, node_id: str):
    for i in proj.intents:
        if i.node_id == node_id:
            return i
    return None


# --- projection ---------------------------------------------------------------------------------------------------------

def _project_objective(ir: RequestIR, o: Objective, base: EffectProjection, tools: list[ToolDeclaration]) -> OperationEffect:
    cond_ids, conditional, approval = _gates(ir, o.id)
    applying = [c.id for c in ev._constraints_applying(ir, o.id)]
    intent = _base_intent(base, o.id)
    base_cls = intent.effect if intent is not None else UNKNOWN
    base_ev = [_evd(e.source, e.span, f"effect_view:{e.kind}", e.text) for e in (intent.evidence if intent else [])]
    cls = ACTION_CLASS[o.action]
    reasons: list[str] = list(intent.reasons) if intent else []

    def mk(operator, primary, potential, unknown_ext, evidence, declared=None, extra_reasons=()):
        complete = "unknown" if (unknown_ext or primary == UNKNOWN) else "known"
        pot = sorted(set(potential) | {primary}) if primary != UNKNOWN else [UNKNOWN]
        return OperationEffect(o.id, o.action, operator, primary, pot, complete, unknown_ext, list(evidence), cond_ids, conditional, approval,
                               applying, o.source_span, declared, reasons + list(extra_reasons))

    # protected / bare-pronoun-head / inform classes: inherit the single-class view
    bare_pronoun = o.target is not None and _BARE_PRONOUN_RE.match(o.target.text) is not None
    if intent is not None and ("objective_inside_protected_region" in intent.reasons or ("head_referent_unresolved" in intent.reasons and bare_pronoun)):
        unknown_ext = o.action == "run"
        return mk(None, UNKNOWN, [UNKNOWN], unknown_ext, base_ev)
    if cls in ("inform", "judge", "propose"):
        return mk(None, REPLY_ONLY, [REPLY_ONLY], False, base_ev or [_evd(o.id, o.source_span, "inform_class", o.action)])

    obj_text = (o.target.text if o.target is not None else "") + " " + (o.trigger.text if o.trigger is not None else "")
    matched = _match_operator(o)
    if o.action == "run":
        if bare_pronoun and (not o.references or any(r.status == "unresolved" for r in o.references)):
            return mk(None, UNKNOWN, [UNKNOWN], True, base_ev + [_evd(o.id, o.target.source_span, "pronoun_operation", o.target.text)], extra_reasons=["pronoun_operation"])
        if bare_pronoun:
            # "Here is the migration dry-run output. … execute it" — typed through the single resolved antecedent; policy still requires
            # resolution (pronoun target). Antecedent without a registry row → unknown external effects.
            ante = _antecedent_text(ir, o)
            # the verb types the operation first ("Restart it" → service_control); the antecedent only when the verb is generic ("run it")
            row = matched[0] if (matched is not None and matched[0].name != "arbitrary_execution" and matched[1].reason.startswith("registry:")
                                 and not _GENERIC_RUN_RE.search(o.trigger.text if o.trigger else "")) else (_registry_row_for_object(ante) if ante else None)
            evidence = base_ev + [_evd(o.id, o.target.source_span, "pronoun_operation", o.target.text), _evd(o.id, None, "antecedent", ante or "")]
            if row is not None:
                return mk(row.name, row.primary, list(row.potential), row.unknown_external, evidence + [_evd(o.id, None, f"registry:{row.name}", ante)],
                          extra_reasons=["pronoun_antecedent_typed"])
            return mk("unlisted_execution", COMMAND_EXECUTION, [COMMAND_EXECUTION], True, evidence, extra_reasons=["pronoun_antecedent_untyped"])
        # declared tool effects are a conservative **union** with registry + text effects; they never narrow (DCE-G1R3C B1.1)
        declared = [t for t in tools if t.matches(obj_text)]
        decl_pot = [c for t in declared for c in t.effects]
        decl_ev = [_evd(f"tool:{t.name}", None, f"tool_declaration:{t.name}", t.scope) for t in declared]
        decl_name = ",".join(t.name for t in declared) or None
        decl_reasons = ["tool_declaration"] if declared else []
        if matched is not None and matched[0].name == "apply_change" and _generic_change_object(o) is not None \
                and re.match(r"\s*(?:appl|make|do|perform|carry|застос)", o.trigger.text if o.trigger else "", _I):
            # "apply the fix" — what is applied, and to what, is not established → unknown (never coerced into an environment change)
            return mk(None, UNKNOWN, [UNKNOWN], False, base_ev + [_generic_change_object(o)], extra_reasons=["ambiguous_medium"])
        if matched is not None:
            row, evd = matched
            pot = list(row.potential) + decl_pot
            evidence = base_ev + [evd] + decl_ev
            for c, e2 in _attributed_effects(o):
                pot.append(c); evidence.append(e2)
            return mk(row.name, row.primary, pot, row.unknown_external, evidence, declared=decl_name, extra_reasons=decl_reasons)
        # an execute verb with an object the registry does not know: behaviour not established — a declaration does not establish it either
        evidence = base_ev + [_evd(o.id, o.trigger.source_span if o.trigger else o.source_span, "registry:unlisted_execution", o.trigger.text if o.trigger else o.text)] + decl_ev
        pot = [COMMAND_EXECUTION] + decl_pot
        for c, e2 in _attributed_effects(o):
            pot.append(c); evidence.append(e2)
        return mk("unlisted_execution", COMMAND_EXECUTION, pot, True, evidence, declared=decl_name, extra_reasons=["unlisted_execution"] + decl_reasons)

    # create / modify / remove
    if matched is not None and matched[0].name in ("service_publish", "deploy"):
        row, evd = matched
        return mk(row.name, row.primary, list(row.potential), False, base_ev + [evd])
    generic = _generic_change_object(o) if o.action in ("create", "modify") else None
    if generic is not None:                        # "make the change", "prepare the changes" — medium not established (sheet v4 rule 18)
        return mk(None, UNKNOWN, [UNKNOWN], False, base_ev + [generic], extra_reasons=["ambiguous_medium"])
    state = _state_object(o)
    if state is not None:
        c, evd = state
        if o.action == "remove" and c == ARTIFACT_WRITE:
            c = base_cls if base_cls in SIDE_EFFECT_CLASSES else ENVIRONMENT_MUTATION
        if base_cls == UNKNOWN and intent is not None and "medium_conflict" in intent.reasons:
            return mk(None, UNKNOWN, [UNKNOWN], False, base_ev + [evd])
        return mk(None, c, [c], False, base_ev + [evd])
    if base_cls in SIDE_EFFECT_CLASSES or base_cls == REPLY_ONLY:
        return mk(None, base_cls, [base_cls], False, base_ev)
    return mk(None, UNKNOWN, [UNKNOWN], False, base_ev)


def _head_action(text: str) -> Optional[str]:
    """The imperative action a clause starts with, when it is a mutate/execute verb ("deploy it", "запусти його")."""
    for action, fam, pat in ACTION_RULES:
        if fam == "imperative" and ACTION_CLASS[action] in ("mutate", "execute") and pat.match(text.lstrip(" ,;:—-")):
            return action
    return None


def _project_unresolved(ir: RequestIR, u: Unresolved, base: EffectProjection) -> Optional[OperationEffect]:
    intent = _base_intent(base, u.id)
    cond_ids, conditional, approval = _gates(ir, u.id)
    if intent is None:
        # "After I approve, deploy it." — a mutate/execute verb whose head object is an unresolved pronoun: an operation of unknown effect
        if u.kind == "ambiguous_referent" and u.rule.endswith(".referent.head"):
            act = _head_action(u.text)
            if act is None:
                return None
            return OperationEffect(u.id, act, None, UNKNOWN, [UNKNOWN], "unknown", act == "run",
                                   [_evd(u.id, u.source_span, "pronoun_operation", u.text)], cond_ids, conditional, approval, [], u.source_span, None,
                                   ["head_referent_unresolved", "pronoun_operation"])
        if u.kind == "vague_object":                   # "Do something with the queue" — a mutating verb with no determinable operand
            return OperationEffect(u.id, None, None, UNKNOWN, [UNKNOWN], "unknown", True,
                                   [_evd(u.id, u.source_span, "vague_object", u.text)], cond_ids, conditional, approval, [], u.source_span, None,
                                   ["vague_object"])
        return None
    unknown_ext = intent.reasons[:1] == ["pronoun_operation"] or (u.kind == "no_recognized_action" and _GENERIC_RUN_RE.search(u.text) is not None)
    return OperationEffect(u.id, None, None, UNKNOWN, [UNKNOWN], "unknown", bool(unknown_ext),
                           [_evd(u.id, u.source_span, f"unresolved:{u.kind}", u.text)], cond_ids, conditional, approval, [], u.source_span, None, list(intent.reasons))


def _expand_prohibited(ir: RequestIR, base: list[ProhibitedEffect]) -> list[ProhibitedEffect]:
    """A forbidden operation forbids **all** of its registry potential effects: "never deploy to production" forbids the
    execution *and* the environment change that deploying implies (sheet v3 §3.5, conservative rule)."""
    out = list(base)
    seen = {(p.effect, p.constraint_id) for p in out}
    by_cid = {c.id: c for c in ir.graph.constraints}
    for c in ir.graph.constraints:                       # "no external changes permitted", "do nothing at all" → every side-effect class
        if c.kind == "prohibition" and _ALL_EFFECTS_PROHIBITED_RE.search(c.text):
            conds = pv.conditions_for(ir, c.id)
            for cls in SIDE_EFFECT_CLASSES:
                if (cls, c.id) not in seen:
                    out.append(ProhibitedEffect(cls, c.id, c.target_action, c.breadth, [q.id for q in conds], any(ev._APPROVAL_RE.search(q.text) for q in conds)))
                    seen.add((cls, c.id))
    for p in base:
        c = by_cid.get(p.constraint_id)
        if c is None:
            continue
        if p.effect == ENVIRONMENT_MUTATION and c.target_action in ("modify", "create") and c.target_object is not None \
                and _UNIVERSAL_OBJECT_RE.match(c.target_object.text) and (ARTIFACT_WRITE, c.id) not in seen:
            out.append(ProhibitedEffect(ARTIFACT_WRITE, c.id, c.target_action, c.breadth, p.deferred_by, p.approval_required))   # "change anything in production"
            seen.add((ARTIFACT_WRITE, c.id))
        if p.effect != COMMAND_EXECUTION:
            continue
        verb_text = c.text if c.target_object is None else c.text[: max(0, c.target_object.source_span.start - c.source_span.start)] or c.text
        if _MULTI_EFFECT_PROHIBITED_RE.search(verb_text) or (c.target_object is not None and _MULTI_EFFECT_PROHIBITED_RE.search(c.target_object.text)):
            if (ENVIRONMENT_MUTATION, c.id) not in seen:
                out.append(ProhibitedEffect(ENVIRONMENT_MUTATION, c.id, c.target_action, c.breadth, p.deferred_by, p.approval_required))
                seen.add((ENVIRONMENT_MUTATION, c.id))
        if _PUBLISH_ROW.trigger is not None and _PUBLISH_ROW.trigger.search(verb_text) and (ENVIRONMENT_MUTATION, c.id) not in seen:
            out.append(ProhibitedEffect(ENVIRONMENT_MUTATION, c.id, c.target_action, c.breadth, p.deferred_by, p.approval_required))   # "do not send anything externally"
            seen.add((ENVIRONMENT_MUTATION, c.id))
    # untyped prohibitions whose verb is a registry operator: "do not promote the canary" → every potential effect of the row
    for c in ir.graph.constraints:
        if c.kind != "prohibition" or c.target_action is not None or any(p.constraint_id == c.id for p in out):
            continue
        for row in OPERATOR_REGISTRY:
            if row.name == "arbitrary_execution" or row.trigger is None or not row.trigger.search(c.text):
                continue
            conds = pv.conditions_for(ir, c.id)
            for cls in row.potential:
                if (cls, c.id) not in seen:
                    out.append(ProhibitedEffect(cls, c.id, None, c.breadth, [q.id for q in conds], any(ev._APPROVAL_RE.search(q.text) for q in conds)))
                    seen.add((cls, c.id))
            break
    out.sort(key=lambda p: (p.constraint_id, p.effect))
    return out


def _pronoun_target(ir: RequestIR, node_id: str) -> bool:
    for o in ir.graph.objectives:
        if o.id == node_id:
            return o.target is not None and ev._PRONOUN_OBJECT_RE.match(o.target.text) is not None
    return False


_PUBLISH_ROW = next(r for r in OPERATOR_REGISTRY if r.name == "service_publish")


def project_operations(ir: RequestIR, tool_declarations: Optional[Iterable[ToolDeclaration]] = None) -> OperationProjection:
    """Project every objective (and every unreadable operation clause) onto an operation-effect record. Pure; deterministic."""
    tools = list(tool_declarations or [])
    base = project_effects(ir)
    ops: list[OperationEffect] = [_project_objective(ir, o, base, tools) for o in ir.graph.objectives]
    for u in ir.graph.unresolved:
        pu = _project_unresolved(ir, u, base)
        if pu is not None:
            ops.append(pu)
    ops.sort(key=lambda x: x.source_span.start)
    side = any(c in SIDE_EFFECT_CLASSES for op in ops for c in op.potential_effects)
    unknown = sum(1 for op in ops if op.primary_operation == UNKNOWN or op.effect_completeness == "unknown")
    prohibited = _expand_prohibited(ir, base.prohibited_effects)
    return OperationProjection(ir.parser_version, OPERATION_PROJECTION_VERSION, ir.digest, ir.status, ops, prohibited,
                               base.unbound_restriction_ids, base.approval_gate_ids, side, unknown, sorted(t.name for t in tools))


# --- policy boundary -----------------------------------------------------------------------------------------------------

def operation_policy(ir: RequestIR, node_id: str, projection: Optional[OperationProjection] = None,
                     tool_declarations: Optional[Iterable[ToolDeclaration]] = None) -> dict:
    """Deny-by-default, read-only reading of the text for **one operation** (an objective or unreadable clause id).

    Returns ``{"decision": DENY | REQUIRE_RESOLUTION | TEXT_NOT_PROHIBITED, "reasons": [...], "operation": {...} | None,
    "prohibited": [classes], "potential": [classes]}``. There is no ``ALLOW``.

    * ``DENY`` — the operation id does not exist; the parser status is not ok/ok_with_unresolved; **any** class in the operation's
      potential effects (registry ∪ text-attributed ∪ tool-declared) is prohibited by the text (deferred "until approval" prohibitions
      included); or the operation has unknown external effects while the text prohibits any side-effect class.
    * ``REQUIRE_RESOLUTION`` — primary ``unknown`` or ``effect_completeness == "unknown"``; conditional or approval-gated; pronoun
      target; unbound restrictions, approval gates, or unresolved nodes anywhere in the request; any other operation with unknown
      effects (the request as a whole is not readable); untraceable source span.
    * ``TEXT_NOT_PROHIBITED`` — otherwise: the text contains a direct, unconditional, unambiguous operation none of whose potential
      effects is forbidden or qualified. Authorization and human approval are outside this library; never execute on this result.
    """
    proj = projection if projection is not None else project_operations(ir, tool_declarations)
    op = proj.operation(node_id)
    proh = {p.effect: p for p in proj.prohibited_effects}
    if op is None:
        return {"decision": DENY, "reasons": [f"no_such_operation:{node_id}"], "operation": None, "prohibited": sorted(proh), "potential": []}
    reasons: list[str] = []
    out = {"operation": asdict(op), "prohibited": sorted(proh), "potential": list(op.potential_effects)}
    if ir.status not in ("ok", "ok_with_unresolved"):
        return {"decision": DENY, "reasons": [f"status:{ir.status}"], **out}
    for c in op.potential_effects:
        if c in proh:
            p = proh[c]
            reasons.append(f"cross_effect_prohibited:{c}:{p.constraint_id}" + (":deferred" if p.deferred_by else ""))
    if op.unknown_external_effects and any(c in proh for c in SIDE_EFFECT_CLASSES):
        reasons.append("unknown_effects_under_prohibition:" + ",".join(sorted(c for c in proh if c in SIDE_EFFECT_CLASSES)))
    if reasons:
        return {"decision": DENY, "reasons": reasons, **out}
    if op.primary_operation == UNKNOWN:
        reasons.append(f"unknown_operation:{op.objective_id}")
    if op.effect_completeness == "unknown":
        reasons.append(f"unknown_external_effects:{op.objective_id}")
    if op.conditional:
        reasons.append(f"conditional:{op.objective_id}:" + ",".join(op.conditions))
    if op.approval_required:
        reasons.append(f"approval_required:{op.objective_id}")
    if any(e.reason in ("pronoun_operation", "effect_view:pronoun_object") for e in op.effect_evidence) or \
            (any(c in SIDE_EFFECT_CLASSES for c in op.potential_effects) and _pronoun_target(ir, op.objective_id)):
        reasons.append(f"pronoun_target:{op.objective_id}")                 # "Apply it to the cluster" — the operand is only known via an antecedent
    for cid in proj.unbound_restriction_ids:
        reasons.append(f"unbound_restriction:{cid}")
    for gid in proj.approval_gate_ids:
        reasons.append(f"approval_gate:{gid}")
    for u in ir.graph.unresolved:
        reasons.append(f"unresolved:{u.id}:{u.kind}")
    for other in proj.operations:
        if other.objective_id != op.objective_id and (other.primary_operation == UNKNOWN or other.effect_completeness == "unknown"):
            reasons.append(f"unknown_effect_elsewhere:{other.objective_id}")
    if op.source_span.end <= op.source_span.start:
        reasons.append(f"untraceable_source:{op.objective_id}")
    return {"decision": REQUIRE_RESOLUTION if reasons else TEXT_NOT_PROHIBITED, "reasons": reasons, **out}
