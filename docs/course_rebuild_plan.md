# Course Project Rebuild Plan

## SQL Conclusion

The project already uses SQL and does not need to be converted into a relational system from scratch.

- ORM: Flask-SQLAlchemy / SQLAlchemy
- Migration layer: Alembic
- Target deployment DB: MySQL
- Test DB: SQLite

What is missing is not SQL itself, but a cleaner course-oriented information model and a tighter feature scope.

## Course Requirements Mapping

Already aligned:

- relational database architecture
- document records and metadata
- PDF upload and recognition
- search and filtering
- batch processing
- web UI

Needs stronger alignment:

- clearer entity boundaries for papers, authors, institutions, venues, and keywords
- cleaner schema naming and deliverable-oriented documentation
- more explicit support for course demo flows
- fewer non-course side features competing for scope

## Modules Worth Keeping

- `app/models.py`: current relational core is already close to a literature management schema
- `app/blueprints/documents.py`: document CRUD, search, attachment handling, PDF recognition
- `app/blueprints/batch_bibtex.py`: batch PDF recognition and import
- `app/services/file_io.py`: attachment persistence
- `app/services/mineru_client.py`: PDF recognition integration
- `app/services/bibtex_io.py`: BibTeX import/export
- `app/blueprints/categories.py`, `library.py`, `settings.py`, `admin.py`: can stay with minor scope cleanup

## Recommended Target Data Model

Primary entities:

- `User`
- `Document`
- `Author`
- `Affiliation`
- `Source` (journal, conference, book series, other)
- `Publisher`
- `Keyword`
- `Tag`
- `Category`
- `File`

Recommended course-facing interpretation:

- `Document` is the main paper / thesis / report record
- `Source` represents venue information
- `Affiliation` represents institution information
- `File` stores uploaded PDFs and other attachments

## Rebuild Strategy

### Phase 1: Scope Freeze

- Keep only course-relevant flows in the UI and docs
- Treat AI journals as optional rather than core
- Avoid reintroducing stamp recognition, A-LSP import, or MARC-generation features

### Phase 2: Schema Hardening

- Review whether `Document`, `Source`, `Publisher`, and `Affiliation` satisfy the course normalization expectations
- Add any missing indexes or uniqueness constraints required by course scenarios
- Keep the migration chain squashed and readable

### Phase 3: Metadata Quality

- Improve PDF recognition post-processing for title, author, venue, DOI, and year
- Add validation rules for incomplete or suspicious metadata
- Add a small review queue or “needs confirmation” marker if recognition confidence is low

### Phase 4: Demo Workflow Polish

- Make the main happy path obvious:
  1. upload PDF
  2. auto-recognize metadata
  3. review and save
  4. search / filter / categorize
  5. export BibTeX if needed
- Ensure screenshots and demo scripts match this flow

### Phase 5: Final Delivery

- Prepare schema explanation and ER diagram
- Prepare a short explanation of SQL usage, normalization choices, and migration strategy
- Prepare sample data and demo PDFs
- Run the key tests before submission

## Suggested Milestones

1. Finish code cleanup and baseline migration
2. Confirm schema against the course PDF and adjust entity relationships if needed
3. Polish PDF recognition and batch import accuracy
4. Prepare final demo dataset and report materials

## Practical Recommendation

Do not rebuild from zero unless the course requires a radically different domain model. The current codebase already has the right relational foundation; the better move is to keep the good modules, tighten the scope, and polish the literature-management workflow end to end.
