Search the library. Each hit is one PDF page or one paragraph, with a url that opens exactly that place; cite that url.

Query grammar: words are ANDed; "a phrase" in double quotes; prefix* (at least 3 letters); a NEAR/5 b; -word excludes. Example: "dangerous capability" evaluat* -cyber. There is no OR: run one search per alternative. There is no stemming: refus* finds refuse, refused and refusal. Vocabulary differs between labs and papers, so try synonyms when a search comes back thin. An empty query lists documents that match the filters.

Filters: kind (paper, system_card, model_card, framework, eval_report, forum_post, blog, article, government, book), org, collection, date_from and date_to (YYYY or YYYY-MM), doc (one document or version id, to search inside it). mode="documents" ranks whole documents by their hits, for triage. sort="date" puts the newest first. limit is 1 to 25; pass next_cursor back as cursor for more.

Snippets are short. Read a hit in full with fetch. Link-only documents return snippets only; check exact wording in them with verify_quote.
