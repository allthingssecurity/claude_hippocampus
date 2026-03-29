// CA3 Associative Memory Layer — Schema Additions
// Run once against existing Neo4j instance at localhost:7475
//
// Adds COACTIVATED relationship support between Entity nodes
// that co-occur within sessions. Does not modify existing schema.

// Index for fast weight-based filtering during spreading activation
CREATE INDEX coactivated_weight IF NOT EXISTS FOR ()-[r:COACTIVATED]-() ON (r.weight);

// Text index for fast entity name lookup during cue seeding
CREATE TEXT INDEX entity_name_text IF NOT EXISTS FOR (e:Entity) ON (e.name);
