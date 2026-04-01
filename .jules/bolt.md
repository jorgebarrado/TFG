## 2024-05-24 - N+1 and Memory exhaustion in Activity Feed
**Learning:** In Django, iterating over a queryset evaluates the entire queryset and loads all objects into memory. If building a combined "activity feed" by fetching all items from multiple tables, sorting them in Python, and then slicing `[:20]`, it results in O(N) memory consumption and N+1 query issues if relations aren't prefetched.
**Action:** Always slice querysets `[:N]` at the database level before loading into Python when building aggregate feeds, and ensure `select_related()` is used for foreign keys accessed in the loop.
