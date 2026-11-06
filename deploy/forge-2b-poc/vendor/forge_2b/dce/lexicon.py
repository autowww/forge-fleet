"""Rule lexicon for DCE-01 request comprehension. Pure regex, no models.

Every pattern is applied to the *original* prompt text with ``re.I`` so match offsets are prompt offsets. Order inside
``OPERATOR_RULES`` is priority: the first operator whose pattern matches a clause wins, so structural verbs
(compare/reconcile/count/audit/list/summarize) beat the generic wh-question fallback (extract).
"""
from __future__ import annotations

import re

W = r"(?<![\w-])"   # word start that also blocks hyphen-joined tokens
E = r"(?![\w-])"

# --- housekeeping / small talk ----------------------------------------------------------------------------------
TASK_PREAMBLE_RE = re.compile(r"\A\s*### Task:", re.I)
GREETING_RE = re.compile(rf"{W}(hi|hello|hey|hiya|yo|thanks|thank you|thx|cheers|good (morning|afternoon|evening)|hello there|hi there|ok|okay|great|cool)(?: there| again)?{E}[!. ]*", re.I)
SEC_DIRECTIVE_RE = re.compile(r"\b10-K\b|\bannual report\b", re.I)

# --- operators (priority order) --------------------------------------------------------------------------------
OPERATOR_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("audit", re.compile(
        r"\b(prompt injection|jailbr\w+|hidden (commands?|instructions?)|instructions? (that )?(try|tries|attempt\w*) to override|"
        r"override (your|the assistant'?s?) (behaviou?r|instructions)|tells? you to ignore|ignore prior instructions|"
        r"(commands?|instructions?) addressed to (the )?assistant|(contain|include)s? (hidden |malicious |suspicious )?(instructions?|commands?)|"
        # live-probe gap (2026-11-05): "does any file try to instruct you?" was no_operator while the legacy scan caught it
        r"(try|tries|trying|attempt\w*) to (instruct|command|direct|manipulate|steer|control|prompt) (you|the assistant|the model|me)|"
        r"instruct(s|ing)? (you|the assistant|the model)|(tell|tells|ask|asks|want|wants) (you|the assistant|the model) to (ignore|disregard|say|reveal|override|forget)|"
        # the user asks us to act on instructions stored *inside* an attachment → deterministic refusal (REFUSE_UNTRUSTED), never execution
        r"(follow|execute|run|apply|obey|carry out|comply with|act on|perform|do) (the |these |those |its |their |all |every |each )?(instructions?|steps|commands?|directives?|orders?|tasks?) (in|from|inside|of|listed in|written in|found in)\b)", re.I)),
    ("reconcile", re.compile(
        r"\b(reconcile|contradict\w*|disagree\w*|conflict\w*|which (one|source|value|file) is (deployed|correct|right|newer|authoritative|true)|"
        r"which (is|one is) (newer|older|current)|the files disagree)\b", re.I)),
    ("compare", re.compile(
        r"\b(compar\w*|differ\w*|difference|vs\.?|versus|against|same as|match(es|ed|ing)?( the| what)?|mismatch\w*|"
        r"(which|what)(?: \w+){0,2} (is|has) (the )?(larger|bigger|smaller|shorter|longer|higher|lower|newer|older|more|less|fewer)|"
        r"what changed|changed between|relate (the )?.* to|as the \w+ requires|as required by|but (present|missing|absent|not) (in|from)|"
        r"not (present|found|listed) in [^,;]* but)\b", re.I)),
    ("count", re.compile(
        r"\Acount\b|\b(count (the|all|every|them|up|me|only)|how many|number of|total( number)? of|wie viele|combien( de)?|cu[aá]nt[oa]s|сколько|скільки|ile|quanti|quante|hoeveel)\b", re.I)),
    ("list", re.compile(
        r"\blist(?: (?:the|all|every|me|its|their|all the))?(?: (?:extracted|included|attached|contained|uploaded|available|readable))? (?:files?|contents?|entries|paths|everything|them|the archive|the zip|the bundle)\b|\Alist\s*$|"
        r"\b(enumerate (the )?files|show (me )?(all )?(the )?(files|contents?|entries|paths)|what files|which files|name the files|print the files|"
        r"(files?|contents?) (are )?(in|of) (this|the) (zip|archive|bundle))\b", re.I)),
    ("summarize", re.compile(
        r"\b(summari[sz]e|summary|overview|describe|tell me about|walk me through|what('s| is) (happening|going on|inside|in (this|here))|"
        r"what does (this|the) (archive|zip|bundle|file) contain|what is this (bundle|archive|zip) about|what is (this|here)|explain (this|the archive|what))\b", re.I)),
    ("recommend", re.compile(r"\b(recommend\w*|suggest\w*|next steps?|what should (we|i)|advi[sc]e|propose)\b", re.I)),
    ("transform", re.compile(
        r"\b(convert|translate|rewrite|reformat|reword|render|format (it|this|that|the \w+) as|output (it |this )?as|"
        r"as (a |an )?(table|json|csv|yaml|markdown|list|bullet points?)|in (json|csv|yaml|markdown) format)\b", re.I)),
    ("validate", re.compile(
        r"\b(validate|verify|confirm|check (whether|if|that)|is it true|are all|were all|did (all|the|every)|does (it|this|that) (pass|hold|comply)|"
        r"is (there|it) (any )?(compliant|valid)|comply|complies)\b", re.I)),
    ("inspect", re.compile(r"\b(inspect|look at|look into|open|examine|review|check)\b", re.I)),
    ("find", re.compile(
        r"\b(find|search( for)?|locate|where (is|does|are)|is there|are there|does\b[^?;,]{0,40}?\b(mention|contain|include|say|refer)|"
        r"did [\w.\-]+ (pass|fail|succeed|break|time out|error)|do any|any (file|line|test|entry) (that|which))\b", re.I)),
    ("extract", re.compile(
        r"\b(extract|quote|pull|retrieve|fetch|get me|give( me)?|provide|return|output|display|print|present|tell me|report|show|identify|name|state|read out|"
        r"what(?:'s| is| are| was| were| does| do| did)?|which|who|whom|whose|when|where|why|how (long|much|big|large|old|often)|whats|"
        r"welche[rsn]?|wie (lange|lang|viel|groß|hoch)|wer|wann|wo|was|quel(le|s|les)?|qui|quand|o[uù]|qu[eé]|qu[ée]l|cu[aá]l(es)?|qui[eé]n|"
        r"d[oó]nde|cu[aá]ndo|какой|какая|какие|кто|когда|где|что|який|яка|які|хто|коли|де|що|jaki|jaka|jakie|kto|kiedy|gdzie|co|ktor[ya])\b", re.I)),
]
OPERATOR_PRIORITY = {op: i for i, (op, _) in enumerate(OPERATOR_RULES)}

# verbs that are imperative but outside the comprehension scope → unresolved(out_of_scope_verb), never a goal
OUT_OF_SCOPE_RE = re.compile(
    r"\b(write|compose|draft|generate|create|make|build|run|execute|launch|start|stop|restart|deploy|install|uninstall|delete|remove|erase|"
    r"modify|edit|change|update|fix|patch|download|upload|send|email|post|browse|visit|navigate|go to|open https?://|"
    r"tell me a joke|sing|draw|play|buy|order|book|call|schedule|remind)\b", re.I)

# --- clause splitting ------------------------------------------------------------------------------------------
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!;])\s+|\n+|\s+—\s+|\s+--\s+")
# connectors that start a new goal clause; ", and <verb>" is handled separately
SEQUENCE_RE = re.compile(r"(,\s*)?\b(and then|then|after that|afterwards|afterward|finally|lastly|secondly|thirdly|followed by|next,)\s*[,:]?\s*", re.I)
AND_VERB_RE = re.compile(r",?\s+\b(and|&|plus|also|as well as)\b\s+(?=\w)", re.I)
ORDER_FIRST_RE = re.compile(r"\b(first(ly)?|start (with|by)|begin (with|by)|to begin|before (anything|answering|that|you answer))\b[,:]?", re.I)
PRECONDITION_RE = re.compile(r"\b(before (answering|replying|you answer|anything)|only after|once you have|after (confirming|checking|verifying))\b", re.I)

# --- constraints --------------------------------------------------------------------------------------------------
NEGATION_RE = re.compile(
    r"(?:\b(?:but|and)\s+)?\b(?:do not|don'?t|never|must not|mustn'?t|should not|shouldn'?t|without|avoid|refrain from|no need to|skip|never mind)\b[^,.;?!]*", re.I)
EXCLUSION_RE = re.compile(
    r"\b(?:excluding|except(?: for)?|other than|apart from|besides|ignore|ignoring|leave out|leaving out|omit|omitting|not including|minus)\b[^,.;?!]*|"
    r"\b(?:neither|nor)\b\s+\w+(?:\s+\w+)?", re.I)
NEG_PREDICATE_RE = re.compile(r"\b(did not|didn'?t|does not|doesn'?t|is not|isn'?t|are not|aren'?t|not present|not in|missing|absent|failed to|unlike)\b[^,.;?!]*", re.I)
SCOPE_ONLY_RE = re.compile(r"\b(only|just|solely|exclusively)\b\s+(?!after\b)[^,.;?!]*", re.I)
OUTPUT_SHAPE_RE = re.compile(
    r"\b(as (a |an )?(table|json|csv|yaml|markdown|list|bullet points?|one line|single sentence)|in (json|csv|yaml|markdown|one sentence|\d+ words)|"
    r"cite (the )?(path|source|line)s?|with (line )?citations|verbatim|exact(ly)?|quote the exact|word for word)\b", re.I)
# Whole clauses that only say *how* to answer or how to treat the input (live-probe gap 2026-11-05: they were parsed as
# extract goals → NOT_RETRIEVED noise, wasted model calls, one DECISION_INVALID node). Matched against a clause, anchored.
CITATION_CLAUSE_RE = re.compile(
    r"^\W*(?:please\s+|and\s+|then\s+|also\s+)*(?:cite|citing|identify|identifying|name|state|mention|include|including|provide|give(?: me)?|show(?: me)?|add|with)\s+"
    r"(?:the\s+|its\s+|their\s+|each\s+|every\s+|all\s+|exact\s+|a\s+|an\s+)*(?:source|citation|reference|evidence|location)s?"
    r"(?:\s+(?:path|file|line|number)s?)*(?:(?:\s+and|\s+or|,|\s+\+|\s+/)\s+(?:the\s+)?(?:exact\s+)?(?:source|path|file|line|number|citation|reference)s?(?:\s+numbers?)?)*\W*$", re.I)
HANDLING_CLAUSE_RE = re.compile(
    r"^\W*(?:please\s+|and\s+|also\s+)*treat\s+(?:the\s+|all\s+|any\s+|every\s+)?(?:file|attachment|archive|zip|document)?\s*(?:contents?|text|data|files?|attachments?|lines?)\s+"
    r"(?:strictly\s+|only\s+)?as\s+(?:untrusted|plain|raw|mere|pure|opaque)?\s*(?:data|text|material|content|input|evidence)\b[^.?!;]*$", re.I)
UPLOAD_PREMISE_RE = re.compile(
    r"^\W*(?:i|we)(?:\s*'?ve|\s+have|\s+just|\s+am|\s+are)*\s+(?:just\s+)?(?:uploaded|attached|added|shared|sent|included|provided|put|dropped|pasted)\b", re.I)
TIME_RE = re.compile(
    r"\b(latest|newest|most recent|recent|last|previous|older|oldest|earlier|current|today|yesterday|now|"
    r"\d{4}-\d{2}(?:-\d{2})?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{4}|q[1-4] \d{4}|fy ?\d{2,4}|v?\d+\.\d+(?:\.\d+)?)\b", re.I)
QUANTITY_RE = re.compile(r"\b(top|first|last|latest|newest|oldest)\s+(\d+|two|three|four|five|ten)\b|\b(\d+|two|three|four|five|ten)\s+(most|largest|smallest|latest)\b", re.I)

# --- targets ----------------------------------------------------------------------------------------------------
PATH_RE = re.compile(r"[\w./\-\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\u4e00-\u9fff]+\.(?:md|txt|json|ya?ml|csv|py|js|ts|toml|xml|html?|sql|log|sh|ini|cfg|conf|rst|tsv)\b", re.I)
QUOTED_RE = re.compile(r"[\"“”'‘’`]([^\"“”'‘’`]{2,80})[\"“”'‘’`]")
IDENT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b[A-Z]{2,}_[A-Z0-9_]+\b")
VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")
EXT_WORDS = {"yaml": ("yaml", "yml"), "yml": ("yaml", "yml"), "csv": ("csv",), "json": ("json",), "html": ("html", "htm"), "markdown": ("md",),
             "python": ("py",), "code": ("py", "js", "ts", "sh"), "text": ("txt",), "config": ("yaml", "yml", "toml", "ini", "cfg", "conf"),
             "configs": ("yaml", "yml", "toml", "ini", "cfg", "conf"), "configuration": ("yaml", "yml", "toml", "ini", "cfg", "conf"),
             "page": ("html", "htm"), "spreadsheet": ("csv", "tsv"), "script": ("py", "sh", "js"), "readme": ("md",), "changelog": ("md",)}
GENERIC_BASENAMES = {"index", "main", "data", "file", "files", "test", "tests", "src", "doc", "docs", "config", "configs", "web", "assets", "notes", "note"}
SEL_RECENCY_RE = re.compile(r"\b(latest|newest|most recent|current|older|oldest|previous|earlier|last)\b", re.I)

# --- language hint ----------------------------------------------------------------------------------------------
LANG_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("uk", re.compile(r"[іїєґ]|\b(який|яка|які|скільки|хто|де|що)\b", re.I)),
    ("ru", re.compile(r"[ыэъё]|\b(какой|какая|какие|сколько|кто|где|что|используется)\b", re.I)),
    ("pl", re.compile(r"[ąęłńśźż]|\b(ile|jaki|jaka|jakie|który|które|jest)\b", re.I)),
    ("de", re.compile(r"[äöüß]|\b(welcher|welche|welches|wie viele|wird|ist|sind|der|die|das|für|und)\b", re.I)),
    ("fr", re.compile(r"\b(quel|quelle|quels|quelles|combien|est|sont|pour|utilisé|utilisée|les|des|du)\b", re.I)),
    ("es", re.compile(r"[¿¡ñ]|\b(qué|cuál|cuáles|cuántas|cuántos|usa|está|están|para|los|las|del)\b", re.I)),
]
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
DECLARATIVE_START_RE = re.compile(r"^\s*(the|a|an|this|that|it|there|i|we|my|our|these|those|he|she|they)\b", re.I)

# words that shape a request but name nothing in the attachments (shared by the quote-relevance gap and the typed key lookup)
REQUEST_WORDS = frozenset("""find quote quotes quoted quoting exact exactly cite cited citing identify show tell give extract list return
provide state name report display print get read locate search check say says mention mentions contain contains include includes its
their string value values line lines path paths source sources file files archive zip attached attachment please also then first
current latest newest configured configuration config setting settings set defined definition specified""".split())
