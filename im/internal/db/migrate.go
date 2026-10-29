package db

import "context"

// migrate 给「已经存在的旧库」补列。
//
// schema.sql 用的是 CREATE TABLE IF NOT EXISTS：新库会直接带上新列，
// 但线上已经跑起来的表不会因为改建表语句就多出一列。教学项目不引入
// migration 框架，用 information_schema 做一层幂等的 ADD COLUMN 即可。
func (s *Store) migrate(ctx context.Context) error {
	type col struct{ table, name, ddl string }
	cols := []col{
		{"users", "dept", "ALTER TABLE users ADD COLUMN dept VARCHAR(64) DEFAULT ''"},
		{"users", "dept_id", "ALTER TABLE users ADD COLUMN dept_id BIGINT DEFAULT 0"},
		{"users", "dept_title", "ALTER TABLE users ADD COLUMN dept_title VARCHAR(64) DEFAULT ''"},
		{"users", "email", "ALTER TABLE users ADD COLUMN email VARCHAR(128) DEFAULT ''"},
		{"users", "phone", "ALTER TABLE users ADD COLUMN phone VARCHAR(32) DEFAULT ''"},
		{"messages", "reply_to", "ALTER TABLE messages ADD COLUMN reply_to BIGINT DEFAULT 0"},
		{"messages", "at_uids", "ALTER TABLE messages ADD COLUMN at_uids VARCHAR(512) DEFAULT ''"},
		{"messages", "recalled", "ALTER TABLE messages ADD COLUMN recalled TINYINT DEFAULT 0"},
	}
	for _, c := range cols {
		var n int
		err := s.DB.QueryRowContext(ctx,
			`SELECT COUNT(*) FROM information_schema.columns
			 WHERE table_schema=DATABASE() AND table_name=? AND column_name=?`,
			c.table, c.name).Scan(&n)
		if err != nil {
			return err
		}
		if n == 0 {
			if _, err := s.DB.ExecContext(ctx, c.ddl); err != nil {
				return err
			}
		}
	}
	return nil
}
