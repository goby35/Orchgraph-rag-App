import json
import os
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

def load_data(filepath: str = "graph_eval.json"):
    """Đọc dữ liệu từ file JSON đã gen ra trước đó."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        print(f"Không tìm thấy {filepath}. Vui lòng kiểm tra lại đường dẫn.")
        return None

def create_dashboard(data: dict):
    # Cài đặt font và style cơ bản
    plt.style.use('ggplot')
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle('GraphRAG Evaluation Dashboard', fontsize=20, fontweight='bold', y=0.98)

    # Lấy dữ liệu
    completeness = data.get("node_completeness", {})
    rels = data.get("relationship_stats", {})
    skills = data.get("skill_normalization", {})
    skill_stats = data.get("skill_stats", {})

    # ==========================================
    # 1. Biểu đồ cột: Node Completeness
    # ==========================================
    ax1 = plt.subplot(2, 2, 1)
    metrics = ['Name', 'Skills', 'Summary', 'Embedding', 'Availability']
    pcts = [
        completeness.get("name_pct", 0),
        completeness.get("skills_pct", 0),
        completeness.get("summary_pct", 0),
        completeness.get("embedding_pct", 0),
        completeness.get("availability_pct", 0)
    ]
    
    bars = ax1.bar(metrics, pcts, color=['#4C72B0', '#55A868', '#C44E52', '#8172B2', '#CCB974'])
    ax1.set_ylim(0, 110)
    ax1.set_title('Node Completeness (%)', fontsize=14, pad=15)
    ax1.set_ylabel('Percentage (%)')
    
    # Gắn label % lên đầu mỗi cột
    for bar in bars:
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2.0, yval + 1, f'{yval}%', ha='center', va='bottom', fontweight='bold')

    # ==========================================
    # 2. Biểu đồ tròn (Donut): Relationship Status
    # ==========================================
    ax2 = plt.subplot(2, 2, 2)
    labels = ['Accepted', 'Pending']
    sizes = [rels.get("accepted", 0), rels.get("pending", 0)]
    colors = ['#55A868', '#F1A340']
    
    if sum(sizes) > 0:
        # Pylance fix: Bỏ unpack biến không dùng đến
        ax2.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', 
                startangle=90, pctdistance=0.85, 
                textprops=dict(color="black", fontweight='bold', fontsize=12))
        
        # Pylance fix: Dùng trực tiếp class Circle từ matplotlib.patches
        centre_circle = Circle((0, 0), 0.70, fc='white')
        ax2.add_artist(centre_circle)
        ax2.text(0, 0, f'Total\n{sum(sizes)}', ha='center', va='center', fontsize=14, fontweight='bold')
    ax2.set_title('CONNECTED_TO Status', fontsize=14, pad=15)

    # ==========================================
    # 3. Biểu đồ cột ngang: Skill Normalization
    # ==========================================
    ax3 = plt.subplot(2, 2, 3)
    norm_labels = ['Before Normalization', 'After Normalization']
    norm_values = [skills.get("before_unique", 0), skills.get("after_unique", 0)]
    
    y_pos = range(len(norm_labels))
    bars_h = ax3.barh(y_pos, norm_values, color=['#4C72B0', '#55A868'], height=0.5)
    ax3.set_yticks(y_pos)
    ax3.set_yticklabels(norm_labels)
    ax3.invert_yaxis()  # Đảo chiều để Before nằm trên
    ax3.set_xlabel('Unique Skills Count')
    ax3.set_title(f'Skill Normalization (Reduction: {skills.get("reduction_pct", 0)}%)', fontsize=14, pad=15)

    # Gắn giá trị lên cột ngang
    for bar in bars_h:
        width = bar.get_width()
        ax3.text(width - (width*0.05), bar.get_y() + bar.get_height()/2.0, 
                 f'{int(width)}', ha='right', va='center', color='white', fontweight='bold')

    # ==========================================
    # 4. Bảng Text (KPIs tổng quan)
    # ==========================================
    ax4 = plt.subplot(2, 2, 4)
    ax4.axis('off') # Tắt trục tọa độ
    
    kpi_text = (
        f"📊 OVERALL STATISTICS\n\n"
        f"👥 Total Personnel: {completeness.get('total', 0)}\n"
        f"🔗 Orphan Rate: {data.get('orphan_rate_pct', 0)}%\n\n"
        f"🛠️ Total Skill Mentions: {skill_stats.get('total_mentions', 0)}\n"
        f"📈 Avg Skills/Person: {skill_stats.get('avg_per_person', 0)}\n"
    )
    
    # Vẽ một khung bao quanh Text
    bbox_props = dict(boxstyle="round,pad=1", fc="#F8F9FA", ec="#ced4da", lw=2)
    ax4.text(0.5, 0.5, kpi_text, ha="center", va="center", fontsize=16, 
             bbox=bbox_props, linespacing=1.5)

    # Lưu biểu đồ và hiển thị
    # Pylance fix: Đổi list sang tuple cho tham số rect
    plt.tight_layout(rect=(0.0, 0.03, 1.0, 0.95))
    output_path = "graph_eval_dashboard.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Đã lưu biểu đồ thành công tại: {os.path.abspath(output_path)}")

def main():
    data = load_data("graph_eval.json")
    if data:
        create_dashboard(data)

if __name__ == "__main__":
    main()