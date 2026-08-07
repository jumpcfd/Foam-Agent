"""Independent review of a case, run in a context of its own.

A case built by one agent and checked by the same agent is checked by whoever decided it
was right. This package runs the check somewhere else: a separate, non-interactive model
session that reads the case files and the specification, and returns its findings as a
document. It never sees how the case was arrived at, and it cannot change anything.

The pieces, imported from the module that owns them rather than re-exported here:

- ``settings``  -- what command to run, with which tools, for how long (YAML)
- ``templates`` -- the tasks it is given, as editable Markdown
- ``channel``   -- starting it, and what to say when it cannot be started
- ``documents`` -- the specification, findings, answers and report a case carries
- ``sandbox``   -- where its arithmetic runs: a container with the case mounted read-only
"""
