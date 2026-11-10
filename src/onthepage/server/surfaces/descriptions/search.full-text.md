Search the library. Each hit is one PDF page or one paragraph, returned with its full text (for openly licensed documents) and a url that opens exactly that place; cite that url.

Query grammar: words are ANDed; "a phrase" in double quotes; prefix* (at least 3 letters); a NEAR/5 b; -word excludes. Example: "dangerous capability" evaluat* -cyber. Vocabulary differs between labs and papers, so try synonyms when a search comes back thin.

Filters: kind (paper, system_card, model_card, framework, eval_report, forum_post, blog, article, government, book), org, collection, date_from and date_to (YYYY or YYYY-MM), doc (one document or version id, to search inside it). limit is 1 to 25; pass next_cursor back as cursor for more. Link-only documents return a short snippet instead of their text.
