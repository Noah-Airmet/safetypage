"""Ingestion: the inventory in ``corpus/scope/`` in, one ``Bundle`` per version out.

``items`` reads the inventory, ``fetch`` fetches politely and keeps every response, ``pdf`` and
``html`` extract the text of record, ``lw`` reads forum posts through GraphQL, ``licence`` makes
each version's licence fact, and ``pipeline`` runs it all. ``python -m onthepage.ingest`` is the
command line.
"""
