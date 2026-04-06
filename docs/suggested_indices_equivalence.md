# Product Equivalence Table Indexing Strategy

## Current Situation
- **Table**: `product_equivalences`
- **Records**: 820,507 product matches
- **Columns**: `source_product_id`, `target_product_id`, `equivalence_type`, `similarity_score`, `created_at`

## Index Strategy: Query-Driven Approach

### Phase 1: Essential Indexes (Implement First)

#### 1. Primary Product Lookup
```sql
CREATE INDEX idx_equivalences_source_product ON product_equivalences (source_product_id);
```
**Use Case**: Find all products equivalent to a given product ID
**Query Pattern**: 
```sql
SELECT target_product_id, equivalence_type, similarity_score 
FROM product_equivalences 
WHERE source_product_id = ?;
```
**Expected Usage**: High frequency - core application feature

#### 2. Quality Filtering
```sql
CREATE INDEX idx_equivalences_type_score ON product_equivalences (equivalence_type, similarity_score DESC);
```
**Use Case**: Find high-quality matches by type and confidence level
**Query Pattern**:
```sql
SELECT * FROM product_equivalences 
WHERE equivalence_type = 'identical' 
ORDER BY similarity_score DESC;
```
**Expected Usage**: Medium frequency - quality assurance and product recommendations

### Phase 2: Performance Optimization (Add If Needed)

#### 3. Bidirectional Product Lookup (Only if needed)
```sql
CREATE INDEX idx_equivalences_target_product ON product_equivalences (target_product_id);
```
**Use Case**: If queries need to find matches regardless of source/target direction
**Query Pattern**:
```sql
SELECT * FROM product_equivalences 
WHERE source_product_id = ? OR target_product_id = ?;
```
**Decision**: Add only if application queries both directions frequently

#### 4. Duplicate Prevention (Only if needed)
```sql
CREATE UNIQUE INDEX idx_equivalences_unique_pair ON product_equivalences (
    LEAST(source_product_id, target_product_id), 
    GREATEST(source_product_id, target_product_id)
);
```
**Use Case**: Prevent duplicate matches (A→B and B→A)
**Decision**: Add only if data integrity requires it

### Phase 3: Maintenance Indexes (Add Later)

#### 5. Time-based Operations
```sql
CREATE INDEX idx_equivalences_created_at ON product_equivalences (created_at);
```
**Use Case**: Data cleanup, batch processing, monitoring recent imports
**Expected Usage**: Low frequency - administrative tasks

## Implementation Recommendations

### Start Small - Measure Impact
1. **Begin with Phase 1 only** (2 indexes)
2. **Monitor query performance** for 1-2 weeks
3. **Add Phase 2 indexes** only if specific slow queries identified
4. **Avoid over-indexing** - each index adds storage cost and slows INSERT/UPDATE

### Index Size Estimates
- **Phase 1**: ~40MB total storage
- **Phase 2**: +30MB additional storage  
- **Phase 3**: +10MB additional storage

### Query Performance Expectations
- **Without indexes**: Product lookup = 2-5 seconds (table scan)
- **With Phase 1**: Product lookup = 1-10ms (index seek)
- **ROI**: 200-5000x performance improvement

## Decision Framework

### Add an index if:
✅ Query runs frequently (>100 times/day)  
✅ Query performance is slow (>500ms)  
✅ Query pattern is predictable and stable  

### Don't add an index if:
❌ Query runs rarely (<10 times/day)  
❌ Query already performs well (<100ms)  
❌ Application doesn't use that query pattern  

## Monitoring Commands

### Check index usage:
```sql
SELECT schemaname, tablename, indexname, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes 
WHERE tablename = 'product_equivalences'
ORDER BY idx_tup_read DESC;
```

### Check index sizes:
```sql
SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) as size
FROM pg_indexes 
WHERE tablename = 'product_equivalences';
```

### Identify slow queries:
```sql
-- Enable slow query logging first
-- Then monitor pg_stat_statements for product_equivalences queries
```

## Implementation SQL

```sql
-- Phase 1: Essential indexes (implement immediately)
CREATE INDEX idx_equivalences_source_product ON product_equivalences (source_product_id);
CREATE INDEX idx_equivalences_type_score ON product_equivalences (equivalence_type, similarity_score DESC);

-- Phase 2: Add only if needed based on actual query patterns
-- CREATE INDEX idx_equivalences_target_product ON product_equivalences (target_product_id);
-- CREATE UNIQUE INDEX idx_equivalences_unique_pair ON product_equivalences (LEAST(source_product_id, target_product_id), GREATEST(source_product_id, target_product_id));

-- Phase 3: Add only for administrative needs
-- CREATE INDEX idx_equivalences_created_at ON product_equivalences (created_at);
```

## Next Steps
1. Implement Phase 1 indexes
2. Test application performance  
3. Monitor actual query patterns for 1-2 weeks
4. Add additional indexes only if specific performance issues identified
5. Review index usage monthly and drop unused indexes