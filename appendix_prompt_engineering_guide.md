# Phụ lục A. Hướng dẫn chuẩn hóa dữ liệu đầu vào (Prompt Engineering Guide)

Phụ lục này được biên soạn dựa trên logic xử lý thực tế của hệ thống ORCHGRAPH-RAG, bao gồm schema đầu vào, cơ chế xếp hạng hybrid search và cách xây dựng ngữ cảnh cho tính năng Digital Twin interview. Mục tiêu là giúp nhà tuyển dụng nhập liệu theo cách tối ưu để tăng độ chính xác truy xuất, đồng thời giảm rủi ro diễn giải sai hoặc bỏ sót thông tin quan trọng.

## A.1. Cơ sở kỹ thuật của hệ thống

Ở lớp API tìm kiếm, endpoint `/search` nhận một payload dạng tự do với trường `query` là chuỗi văn bản mô tả nhu cầu tuyển dụng. Về mặt schema, hệ thống không yêu cầu JD ở dạng JSON bắt buộc, nhưng phần nội dung nên được viết sao cho các tín hiệu kỹ thuật có thể được nhận diện rõ ràng.

Schema hiện hành của request tìm kiếm gồm ba trường:
- `query`: nội dung JD dạng chuỗi tự do;
- `top_k`: số lượng ứng viên trả về;
- `include_explanation`: bật hoặc tắt phần giải thích mức độ phù hợp.

Ở lớp mô hình dữ liệu, các node nhân sự được biểu diễn theo `RecruitmentNode`, trong đó:
- `public_data.skills` là danh sách kỹ năng công khai.
- `public_data.experience.tech_stack` là danh sách công nghệ dùng trong từng trải nghiệm.
- `public_data.education.degree` và `public_data.education.year` là các trường học vấn đã được chuẩn hóa.
- `private_data.salary_expectation`, `private_data.project_technical_secrets`, `private_data.blacklist_orgs` là dữ liệu riêng tư.

Về cơ chế xếp hạng, hệ thống hiện tại dùng công thức lai giữa đồ thị và vector:
- Điểm cuối cùng được tính theo tỉ trọng xấp xỉ `0.2 * S_graph + 0.8 * S_vector`.
- `S_graph` ở chế độ tăng cường được tổng hợp từ ba thành phần: độ khớp kỹ năng Jaccard, thành phần thâm niên và tín hiệu thưởng khi có trùng công nghệ liên kết.
- Điểm thâm niên được suy ra từ số lượng kinh nghiệm trong graph, rồi quy đổi nội bộ theo công thức gần đúng `years = experience_count * 2`.
- Tín hiệu thưởng (`bonus_component`) chỉ bật khi kỹ năng trong JD giao nhau với tập công nghệ liên kết của ứng viên; trong code hiện tại đây là một tín hiệu nhị phân, không phải một điểm cộng tuyến tính phức tạp.

Ở lớp Digital Twin, hệ thống dựng ngữ cảnh từ Supabase theo hai vùng rõ ràng: công khai và riêng tư. Private chunk chỉ được đưa vào ngữ cảnh khi quan hệ `CONNECTED_TO` có trạng thái `accepted`. Khi hợp lệ, private blob được gắn nhãn chuẩn hóa như `[Lương kỳ vọng]`, `[Bí mật kỹ thuật]`, `[Blacklist]`. Các chunk dài còn được cắt theo cửa sổ ngữ nghĩa để ưu tiên đoạn liên quan trực tiếp đến câu hỏi.

## A.2. Tối ưu hóa truy vấn tuyển dụng (Job Description - JD)

### 1. Viết kỹ năng theo dạng rút gọn, tách bạch và nhất quán

Hệ thống tách tín hiệu kỹ năng bằng dấu xuống dòng, dấu phẩy, dấu chấm phẩy, dấu gạch đứng và một số mẫu phân tách văn bản khác. Vì vậy, cách viết hiệu quả nhất là liệt kê kỹ năng thành các token rõ ràng, mỗi kỹ năng là một đơn vị riêng biệt.

Nên dùng:
- `python`
- `fastapi`
- `postgres`
- `kubernetes`
- `docker`
- `react`

Nên tránh:
- Viết kỹ năng thành câu dài, ví dụ: “thành thạo phát triển backend hiện đại, cloud-native, containerization và microservices”.
- Trộn quá nhiều mô tả mềm vào cùng một dòng kỹ năng.
- Dùng tên gọi mơ hồ như “framework phổ biến”, “công nghệ mới”, “hệ thống lớn”.

Do có cơ chế chuẩn hóa alias, các biến thể như `ReactJS`, `NodeJS`, `K8s`, `PostgreSQL` có thể được quy về dạng chuẩn. Tuy nhiên, để tăng độ khớp, vẫn nên ưu tiên viết trực tiếp tên canonical mà hệ thống lưu trong graph, ví dụ `react`, `node.js`, `kubernetes`, `postgres`.

### 2. Ưu tiên mô tả cụ thể thay vì mô tả chung chung

Phần vector search trong hệ thống vẫn dựa mạnh vào ngữ nghĩa của toàn bộ JD. Vì vậy, nếu muốn ứng viên được xếp đúng hơn, JD nên nêu rõ:
- vai trò cụ thể;
- bộ công nghệ trọng tâm;
- môi trường triển khai;
- domain nghiệp vụ;
- quy mô hoặc độ phức tạp hệ thống.

Ví dụ tốt:
- “Xây dựng API backend bằng `python`, `fastapi`, `postgres`, `redis`.”
- “Triển khai hạ tầng container với `docker` và `kubernetes`.”
- “Làm việc với hệ thống phỏng vấn realtime, truy xuất dữ liệu đồ thị và semantic search.”

### 3. Ghi số năm kinh nghiệm rõ ràng

Hiện tại, hệ thống không có một bộ lọc cứng tách riêng số năm kinh nghiệm từ JD. Tuy nhiên, tín hiệu về thâm niên vẫn ảnh hưởng tới xếp hạng tổng qua thành phần graph và vector. Vì vậy, nhà tuyển dụng nên viết thẳng mức kinh nghiệm theo chuẩn định lượng:
- `2 năm kinh nghiệm`
- `3-5 năm kinh nghiệm`
- `5+ năm kinh nghiệm`
- `tối thiểu 7 năm kinh nghiệm`

Nên tránh:
- `nhiều năm kinh nghiệm`
- `senior level`
- `đã làm lâu năm`

Lý do là các mô tả mơ hồ này không tạo tín hiệu đủ mạnh cho mô hình ngữ nghĩa, trong khi con số cụ thể giúp hệ thống bám sát ý định hơn và giúp phần giải thích kết quả rõ ràng hơn.

### 4. Bảng so sánh JD mẫu kém và JD mẫu tối ưu

| Thành phần | JD mẫu kém | JD mẫu tối ưu | Lý do cải thiện |
|---|---|---|---|
| Tiêu đề | Tìm người giỏi công nghệ | Senior Backend Engineer | Nêu rõ vai trò giúp vector search nhận diện đúng nhiệm vụ |
| Kỹ năng | Làm việc với các framework hiện đại | `python`, `fastapi`, `postgres`, `redis`, `docker` | Kỹ năng được tách thành token rõ ràng, dễ khớp Jaccard |
| Kinh nghiệm | Có nhiều năm làm backend | `3-5 năm kinh nghiệm backend`, `2+ năm hệ thống phân tán` | Số liệu cụ thể tạo tín hiệu tốt hơn cho semantic matching |
| Domain | Dự án đa dạng | API tuyển dụng, graph retrieval, semantic search | Domain cụ thể giúp mô hình vector hiểu ngữ cảnh |
| Phạm vi công việc | Phát triển sản phẩm | Thiết kế API, tối ưu truy vấn, phối hợp dữ liệu Neo4j và Supabase | Mô tả có động từ và đối tượng rõ ràng |
| Mức độ ưu tiên | Ưu tiên người phù hợp | Ưu tiên người có kinh nghiệm với `fastapi`, `neo4j`, `supabase`, `kubernetes` | Tăng giao nhau giữa JD skills và graph skills |

### 5. Mẫu JD khuyến nghị

```text
Vị trí: Senior Backend Engineer

Kỹ năng cốt lõi:
- python
- fastapi
- postgres
- redis
- docker
- kubernetes
- neo4j
- supabase

Kinh nghiệm:
- 3-5 năm kinh nghiệm backend
- Có kinh nghiệm với hệ thống phân tán hoặc semantic search
- Ưu tiên ứng viên từng làm với graph database và vector database

Mô tả công việc:
- Thiết kế và phát triển API
- Tối ưu hiệu năng truy vấn
- Làm việc với kiến trúc đa cơ sở dữ liệu
- Phối hợp với các luồng truy xuất ngữ nghĩa và dữ liệu đồ thị
```

## A.3. Nghệ thuật phỏng vấn Bản sao số (Digital Twin Prompting)

### 1. Sử dụng cấu trúc STAR để kích hoạt truy xuất ngữ nghĩa tốt hơn

Hệ thống Digital Twin truy xuất các chunk ngữ nghĩa từ Supabase. Các câu hỏi có cấu trúc rõ ràng, bám vào tình huống thực tế sẽ giúp mô hình cắt chunk tốt hơn và tập trung vào đoạn có liên quan nhất.

Khuyến nghị dùng cấu trúc STAR:
- **Situation**: bối cảnh/dự án nào;
- **Task**: mục tiêu hoặc trách nhiệm gì;
- **Action**: đã làm gì;
- **Result**: kết quả đo lường được là gì.

Ví dụ tốt:
- “Trong dự án X, bạn đã tối ưu latency như thế nào? Hãy mô tả bối cảnh, hành động, và kết quả đo được.”
- “Ở hệ thống Y, bạn xử lý vấn đề dữ liệu trùng lặp ra sao, và tác động cuối cùng là gì?”
- “Bạn đã triển khai `kubernetes` hoặc `fastapi` trong tình huống nào, và vì sao chọn cách đó?”

Cách hỏi này giúp hệ thống dễ tìm đúng chunk chứa kinh nghiệm, số liệu và bối cảnh.

### 2. Đặt câu hỏi theo từng ý chính, không dồn nhiều mục tiêu trong một câu

Nên hỏi một chủ đề mỗi lần. Ví dụ:
- Một câu hỏi về kỹ năng;
- Một câu hỏi về một dự án;
- Một câu hỏi về một kết quả cụ thể;
- Một câu hỏi về kinh nghiệm phối hợp hoặc ra quyết định.

Không nên hỏi kiểu:
- “Hãy nói về dự án, lương, bí mật kỹ thuật, và lý do nghỉ việc của bạn.”

Những câu hỏi đa mục tiêu dễ làm nhiễu ngữ cảnh và giảm khả năng mô hình trả lời đúng trọng tâm.

### 3. Giới hạn của hệ thống cần được tôn trọng

Digital Twin chỉ trả lời tốt khi thông tin đã có trong hồ sơ hoặc chunk riêng tư hợp lệ. Vì vậy:
- Nếu hỏi về thông tin không nằm trong hồ sơ, hệ thống có thể trả về trạng thái kiểu `NOT_FOUND` hoặc câu trả lời an toàn.
- Nếu hỏi suy diễn tương lai, ví dụ “năm sau bạn sẽ làm gì”, hệ thống thường không có đủ căn cứ để suy luận và sẽ không nên ép mô hình đoán.
- Nếu quan hệ truy cập chưa được chấp nhận, phần dữ liệu riêng tư sẽ không xuất hiện trong ngữ cảnh.

Do đó, nhà tuyển dụng nên ưu tiên câu hỏi về dữ liệu đã có thực trong hồ sơ hơn là các giả định ngoài phạm vi.

### 4. Mẫu câu hỏi hiệu quả

- “Trong dự án gần nhất, bạn chịu trách nhiệm phần nào?”
- “Bạn đã dùng công nghệ gì để giải quyết vấn đề đó?”
- “Kết quả sau khi tối ưu là gì, có số liệu cụ thể không?”
- “Bạn có thể mô tả rõ hơn bối cảnh, hành động và kết quả của dự án này không?”
- “Nếu có một điểm mạnh kỹ thuật nổi bật nhất, đó là gì và được thể hiện ở đâu trong dự án?”

## A.4. Keywords & Formats khuyên dùng

### 1. Quy tắc định dạng nên áp dụng

- Viết kỹ năng bằng chữ thường: `python`, `fastapi`, `postgres`, `kubernetes`.
- Tách kỹ năng thành từng mục riêng, ưu tiên xuống dòng hoặc danh sách gạch đầu dòng.
- Dùng tên công nghệ chuẩn thay vì biệt danh hoặc mô tả chung chung.
- Dùng số liệu cụ thể khi nêu kinh nghiệm: `3 năm`, `5+ năm`, `25%`, `100ms`, `USD 2,000`.
- Dùng một ý chính cho mỗi câu hỏi phỏng vấn.
- Ưu tiên động từ hành động: “thiết kế”, “triển khai”, “tối ưu”, “đánh giá”, “giảm”, “cải thiện”.

### 2. Từ khóa nên ưu tiên trong JD

- `python`
- `fastapi`
- `neo4j`
- `supabase`
- `postgres`
- `redis`
- `docker`
- `kubernetes`
- `semantic search`
- `graph database`
- `vector database`
- `distributed system`
- `api`
- `backend`

### 3. Từ khóa nên ưu tiên trong câu hỏi phỏng vấn

- `dự án`
- `bối cảnh`
- `trách nhiệm`
- `hành động`
- `kết quả`
- `tối ưu`
- `latency`
- `throughput`
- `chi phí`
- `scale`
- `trade-off`
- `nguyên nhân`

### 4. Dạng dữ liệu nên tránh

- Mô tả mơ hồ, nhiều tính từ nhưng ít kỹ thuật.
- Một câu dài chứa quá nhiều yêu cầu.
- Kỹ năng viết theo văn phong marketing thay vì văn phong kỹ thuật.
- Số liệu không nhất quán hoặc không có đơn vị.
- Cụm từ suy diễn như “rất mạnh”, “khá nhiều”, “có kinh nghiệm tốt”.

## A.5. Kết luận thực hành

Để ORCHGRAPH-RAG trả về kết quả chính xác hơn, nhà tuyển dụng nên xem JD như một bản đặc tả kỹ thuật ngắn gọn, có cấu trúc, dùng đúng tên công nghệ và số liệu rõ ràng. Với Digital Twin, câu hỏi nên đi theo STAR, tập trung vào dữ liệu đã có trong hồ sơ và tránh các yêu cầu suy diễn ngoài phạm vi. Cách nhập liệu này phù hợp trực tiếp với logic Jaccard + vector search, cơ chế chuẩn hóa kỹ năng, và cách hệ thống dựng ngữ cảnh phỏng vấn trong code hiện hành.
