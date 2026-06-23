"""WHO/Europe speech-writer proof-of-concept.

A parallel application of the ODMI agent-swarm architecture (researcher /
verifier / adjudicator, with honest abstention and a quote-level provenance
gate) to a new domain: producing defensible, sourced speaking points for the
WHO Regional Office for Europe from its published record in the IRIS
repository.

The pipeline is a coarse-to-fine funnel:

    IRIS (EURO subtree)  ->  Docling extraction  ->  provenance chunking
        ->  LanceDB hybrid retrieval  ->  researcher/verifier/adjudicator
        ->  briefing pack of verbatim, cited, licence-cleared points

Every layer here is new code; the agent spine is forked from `agents/` later.
This package has no dependency on the ODMI code and is self-contained.
"""

__version__ = "0.1.0"
