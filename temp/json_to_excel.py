import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.chart import BarChart, Reference
from openpyxl.utils import get_column_letter

# Sample JSON data mirroring the structure
json_data = [
    {
        "case_id": 101,
        "title": "Verify Login Functionality",
        "assignedto_id": "John Doe",
        "defects": "DEF-001",
        "environment": "Staging",
        "section_hierarchy": "Authentication > Login",
        "status0": "Fail",
        "comment0": "Password field throws 500 error.",
        "status1": "Pass",
        "comment1": "Fixed in patch v1.1."
    },
    {
        "case_id": 102,
        "title": "Verify Logout Flow",
        "assignedto_id": "Jane Smith",
        "defects": "",
        "environment": "Production",
        "section_hierarchy": "Authentication > Logout",
        "status0": "Pass",
        "comment0": "Session cleared successfully.",
        "status1": "Fail",
        "comment1": "Cookie persistent on some browsers."
    }
]

def json_to_excel_with_summary(data, output_file="summary_report.xlsx"):
    wb = openpyxl.Workbook()

    # ==========================================
    # --- SHEET 1: Json to Excel ---
    # ==========================================
    ws1 = wb.active
    ws1.title = "Json to Excel"

    # 1. Identify all dynamic status/comment pairs across all records
    max_status_index = -1
    for item in data:
        for key in item.keys():
            if key.startswith("status") and key[6:].isdigit():
                idx = int(key[6:])
                if idx > max_status_index:
                    max_status_index = idx

    # 2. Define Base Headers & Dynamic Status Headers
    headers = [
        "Case ID", "Title", "Assigned To ID", "Defects", 
        "Environment", "Section Hierarchy"
    ]
    
    # Add historical status columns dynamically
    for i in range(max_status_index):
        headers.extend([f"Status {i}", f"Comment {i}"])
        
    # Append the Latest Status columns to the end
    headers.extend(["Latest Status", "Latest Comment"])
    ws1.append(headers)
    
    # 3. Populate Rows
    for item in data:
        row = [
            item.get("case_id", ""),
            item.get("title", ""),
            item.get("assignedto_id", ""),
            item.get("defects", ""),
            item.get("environment", ""),
            item.get("section_hierarchy", "")
        ]
        
        # Populate historical status pairs
        for i in range(max_status_index):
            row.extend([item.get(f"status{i}", ""), item.get(f"comment{i}", "")])
            
        # Extract the highest indexed status ("Latest")
        latest_status = item.get(f"status{max_status_index}", "")
        latest_comment = item.get(f"comment{max_status_index}", "")
        
        row.extend([latest_status, latest_comment])
        ws1.append(row)
        
    # 4. Styling and Formatting for Sheet 1
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")
    
    for cell in ws1[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        
    for col in ws1.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row > 1:
                cell.font = Font(name="Segoe UI", size=10)
                if "Status" in str(ws1.cell(row=1, column=cell.column).value):
                    cell.alignment = center_align
                else:
                    cell.alignment = left_align
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws1.column_dimensions[col_letter].width = max(max_len + 4, 14)
        
    ws1.freeze_panes = "A2"

    # ==========================================
    # --- SHEET 2: Detailed Summary ---
    # ==========================================
    ws2 = wb.create_sheet(title="Detailed Summary")

    # Title Block
    ws2.merge_cells("A1:D1")
    ws2["A1"] = "Test Execution Summary Report"
    ws2["A1"].font = Font(name="Segoe UI", size=16, bold=True, color="1F4E78")
    ws2["A1"].alignment = left_align
    ws2.row_dimensions[1].height = 30

    ws2.merge_cells("A2:D2")
    ws2["A2"] = "Overview of test case distribution, status metrics, and environment breakdown."
    ws2["A2"].font = Font(name="Segoe UI", size=10, italic=True, color="595959")
    ws2.row_dimensions[2].height = 18

    # Summary Table 1: Latest Status Breakdown
    ws2["A4"] = "Latest Status Distribution"
    ws2["A4"].font = Font(name="Segoe UI", size=12, bold=True, color="1F4E78")

    sum_headers = ["Status", "Count", "Percentage"]
    for col_num, h in enumerate(sum_headers, 1):
        cell = ws2.cell(row=5, column=col_num)
        cell.value = h
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    statuses = ["Pass", "Fail", "Blocked", "Not Run"]
    last_row_data = len(data) + 1  # Header is row 1, data rows follow
    latest_col_letter = get_column_letter(len(headers) - 1)

    for idx, status in enumerate(statuses, 6):
        ws2.cell(row=idx, column=1, value=status).alignment = left_align
        
        # Dynamic COUNTIF formula referencing Sheet 1
        count_formula = f"=COUNTIF('Json to Excel'!${latest_col_letter}$2:${latest_col_letter}${last_row_data}, A{idx})"
        ws2.cell(row=idx, column=2, value=count_formula).alignment = center_align
        
        # Percentage formula
        pct_formula = f"=B{idx}/COUNTA('Json to Excel'!$A$2:$A${last_row_data})"
        cell_pct = ws2.cell(row=idx, column=3, value=pct_formula)
        cell_pct.number_format = '0.0%'
        cell_pct.alignment = center_align

        for c in range(1, 4):
            ws2.cell(row=idx, column=c).font = Font(name="Segoe UI", size=10)

    # Status Total Row
    total_row = 6 + len(statuses)
    ws2.cell(row=total_row, column=1, value="Total").font = Font(name="Segoe UI", size=10, bold=True)
    ws2.cell(row=total_row, column=2, value=f"=SUM(B6:B{total_row-1})").font = Font(name="Segoe UI", size=10, bold=True)
    ws2.cell(row=total_row, column=2).alignment = center_align
    ws2.cell(row=total_row, column=3, value=f"=SUM(C6:C{total_row-1})").font = Font(name="Segoe UI", size=10, bold=True)
    ws2.cell(row=total_row, column=3).number_format = '0.0%'
    ws2.cell(row=total_row, column=3).alignment = center_align

    # Summary Table 2: Environment Breakdown
    ws2["E4"] = "Environment Breakdown"
    ws2["E4"].font = Font(name="Segoe UI", size=12, bold=True, color="1F4E78")

    env_headers = ["Environment", "Total Cases"]
    for col_num, h in enumerate(env_headers, 5):
        cell = ws2.cell(row=5, column=col_num)
        cell.value = h
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    envs = ["Staging", "Production", "Development", "UAT"]
    for idx, env in enumerate(envs, 6):
        ws2.cell(row=idx, column=5, value=env).alignment = left_align
        env_count_formula = f"=COUNTIF('Json to Excel'!$E$2:$E${last_row_data}, E{idx})"
        ws2.cell(row=idx, column=6, value=env_count_formula).alignment = center_align
        for c in range(5, 7):
            ws2.cell(row=idx, column=c).font = Font(name="Segoe UI", size=10)

    # Environment Total Row
    ws2.cell(row=total_row, column=5, value="Total").font = Font(name="Segoe UI", size=10, bold=True)
    ws2.cell(row=total_row, column=6, value=f"=SUM(F6:F{total_row-1})").font = Font(name="Segoe UI", size=10, bold=True)
    ws2.cell(row=total_row, column=6).alignment = center_align

    # Add Bar Chart for Status Breakdown
    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    chart.title = "Latest Status Overview"
    chart.y_axis.title = "Number of Test Cases"
    chart.x_axis.title = "Status"

    data_ref = Reference(ws2, min_col=2, min_row=5, max_row=total_row-1)
    cats_ref = Reference(ws2, min_col=1, min_row=6, max_row=total_row-1)
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.legend = None
    chart.width = 14
    chart.height = 7.5

    ws2.add_chart(chart, f"A{total_row + 2}")

    # Adjust column widths for Sheet 2
    for col in ws2.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws2.column_dimensions[col_letter].width = max(max_len + 6, 16)

    wb.save(output_file)
    print(f"Excel report successfully generated and saved to: {output_file}")

# Execute script
if __name__ == "__main__":
    json_to_excel_with_summary(json_data)