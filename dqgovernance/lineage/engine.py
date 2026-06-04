from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import json

from ..utils import ConfigManager, DatabaseManager
from ..logging import DQLogger


class LineageEngine:
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager()
        self.logger = DQLogger()
        self.enable = self.config.get("lineage.enable", True)

    def update_lineage(
        self,
        source_system: str,
        source_table: str,
        source_field: Optional[str] = None,
        target_system: Optional[str] = None,
        target_table: Optional[str] = None,
        target_field: Optional[str] = None,
        transformation_rule: Optional[str] = None,
        quality_status: str = "normal",
    ) -> int:
        if not self.enable:
            self.logger.debug("数据血缘功能未启用，跳过更新")
            return 0

        data = {
            "source_system": source_system,
            "source_table": source_table,
            "source_field": source_field,
            "target_system": target_system,
            "target_table": target_table,
            "target_field": target_field,
            "transformation_rule": transformation_rule,
            "quality_status": quality_status,
            "last_verified_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        existing = self.db.execute_query(
            """SELECT id FROM data_lineage 
               WHERE source_system = ? AND source_table = ? 
               AND COALESCE(source_field, '') = COALESCE(?, '')
               AND COALESCE(target_system, '') = COALESCE(?, '')
               AND COALESCE(target_table, '') = COALESCE(?, '')
               AND COALESCE(target_field, '') = COALESCE(?, '')""",
            (
                source_system,
                source_table,
                source_field or "",
                target_system or "",
                target_table or "",
                target_field or "",
            ),
        )

        try:
            if existing:
                lineage_id = self.db.update_record(
                    "data_lineage",
                    data,
                    "id = ?",
                    (existing[0]["id"],),
                )
                self.logger.debug(f"更新数据血缘: {source_system}.{source_table} -> {target_system}.{target_table}")
            else:
                lineage_id = self.db.insert_record("data_lineage", data)
                self.logger.info(f"创建数据血缘: {source_system}.{source_table} -> {target_system}.{target_table}")

            self.logger.log_operation(
                "lineage_update",
                {
                    "source_system": source_system,
                    "source_table": source_table,
                    "source_field": source_field,
                    "target_system": target_system,
                    "target_table": target_table,
                    "target_field": target_field,
                    "quality_status": quality_status,
                },
                system_code=source_system,
            )

            return lineage_id
        except Exception as e:
            self.logger.error(f"更新数据血缘失败: {e}", exc_info=True)
            return 0

    def mark_quality_status(
        self,
        system_code: str,
        table_name: str,
        field_name: Optional[str] = None,
        quality_status: str = "normal",
    ) -> bool:
        if not self.enable:
            return False

        update_data = {
            "quality_status": quality_status,
            "last_verified_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        query_conditions = "source_system = ? AND source_table = ?"
        params = [system_code, table_name]

        if field_name:
            query_conditions += " AND source_field = ?"
            params.append(field_name)

        try:
            self.db.update_record(
                "data_lineage",
                update_data,
                query_conditions,
                tuple(params),
            )
            self.logger.info(
                f"标记数据血缘质量状态: {system_code}.{table_name}"
                f"{'.' + field_name if field_name else ''} = {quality_status}"
            )
            return True
        except Exception as e:
            self.logger.error(f"标记质量状态失败: {e}", exc_info=True)
            return False

    def get_lineage(
        self,
        system_code: Optional[str] = None,
        table_name: Optional[str] = None,
        field_name: Optional[str] = None,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        if not self.enable:
            return []

        query = "SELECT * FROM data_lineage WHERE 1=1"
        params = []

        if direction == "downstream" and system_code:
            query += " AND source_system = ?"
            params.append(system_code)
            if table_name:
                query += " AND source_table = ?"
                params.append(table_name)
            if field_name:
                query += " AND source_field = ?"
                params.append(field_name)

        elif direction == "upstream" and system_code:
            query += " AND target_system = ?"
            params.append(system_code)
            if table_name:
                query += " AND target_table = ?"
                params.append(table_name)
            if field_name:
                query += " AND target_field = ?"
                params.append(field_name)

        elif direction == "both" and system_code:
            query += " AND (source_system = ? OR target_system = ?)"
            params.extend([system_code, system_code])

        query += " ORDER BY created_at DESC"
        return self.db.execute_query(query, tuple(params))

    def get_lineage_graph(
        self,
        system_code: str,
        depth: int = 3,
    ) -> Dict[str, Any]:
        if not self.enable:
            return {"nodes": [], "edges": []}

        nodes = set()
        edges = []

        def traverse(current_system: str, current_depth: int, visited: set):
            if current_depth > depth or current_system in visited:
                return

            visited.add(current_system)
            nodes.add(current_system)

            lineages = self.get_lineage(current_system, direction="downstream")
            for lineage in lineages:
                if lineage.get("target_system"):
                    target = lineage["target_system"]
                    edges.append(
                        {
                            "source": current_system,
                            "target": target,
                            "source_table": lineage.get("source_table"),
                            "target_table": lineage.get("target_table"),
                            "transformation": lineage.get("transformation_rule"),
                            "quality_status": lineage.get("quality_status"),
                        }
                    )
                    traverse(target, current_depth + 1, visited.copy())

        traverse(system_code, 0, set())

        return {
            "nodes": list(nodes),
            "edges": edges,
            "root_system": system_code,
            "max_depth": depth,
        }

    def get_impact_analysis(
        self,
        system_code: str,
        table_name: Optional[str] = None,
        field_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enable:
            return {"downstream_systems": [], "affected_tables": 0, "affected_fields": 0}

        downstream = self.get_lineage(system_code, table_name, field_name, direction="downstream")

        systems = set()
        tables = set()
        fields = set()

        for lineage in downstream:
            if lineage.get("target_system"):
                systems.add(lineage["target_system"])
            if lineage.get("target_table"):
                tables.add(f"{lineage['target_system']}.{lineage['target_table']}")
            if lineage.get("target_field"):
                fields.add(
                    f"{lineage['target_system']}.{lineage['target_table']}.{lineage['target_field']}"
                )

        return {
            "downstream_systems": list(systems),
            "affected_tables": list(tables),
            "affected_fields": list(fields),
            "total_systems": len(systems),
            "total_tables": len(tables),
            "total_fields": len(fields),
            "original_source": {
                "system": system_code,
                "table": table_name,
                "field": field_name,
            },
        }

    def update_lineage_from_quality_results(
        self,
        system_code: str,
        quality_results: List[Dict[str, Any]],
    ) -> int:
        if not self.enable:
            return 0

        updated_count = 0
        for result in quality_results:
            table_name = result.get("table_name")
            overall_score = result.get("overall_score", 100)

            if overall_score >= 90:
                quality_status = "excellent"
            elif overall_score >= 80:
                quality_status = "good"
            elif overall_score >= 60:
                quality_status = "warning"
            else:
                quality_status = "critical"

            if self.mark_quality_status(system_code, table_name, quality_status=quality_status):
                updated_count += 1

        self.logger.info(
            f"根据质量结果更新数据血缘质量状态，共更新 {updated_count} 条记录"
        )
        return updated_count

    def get_lineage_statistics(self) -> Dict[str, Any]:
        if not self.enable:
            return {"enabled": False}

        all_lineage = self.db.execute_query("SELECT * FROM data_lineage")

        stats = {
            "enabled": True,
            "total_relationships": len(all_lineage),
            "by_quality_status": {},
            "by_source_system": {},
            "by_target_system": {},
            "with_transformation": 0,
        }

        for lineage in all_lineage:
            status = lineage.get("quality_status", "unknown")
            stats["by_quality_status"][status] = (
                stats["by_quality_status"].get(status, 0) + 1
            )

            source = lineage.get("source_system", "unknown")
            stats["by_source_system"][source] = (
                stats["by_source_system"].get(source, 0) + 1
            )

            target = lineage.get("target_system")
            if target:
                stats["by_target_system"][target] = (
                    stats["by_target_system"].get(target, 0) + 1
                )

            if lineage.get("transformation_rule"):
                stats["with_transformation"] += 1

        return stats
