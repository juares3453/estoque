from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    send_file,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, timedelta
from dotenv import load_dotenv, find_dotenv
from sqlalchemy import text

import os
from pathlib import Path
import io
try:
    import pandas as pd
except Exception:
    pd = None

try:
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
except Exception:
    # If reportlab not installed, PDF export will fail later with a clear error
    pass

# Carrega o .env do repositório (procura em parents se necessário)
load_dotenv(find_dotenv())

app = Flask(__name__)
# Configurando o SQLAlchemy para PostgreSQL
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
# Usa `SECRET_KEY` se definido, senão tenta `SESSION_KEY` (compatibilidade)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or os.getenv("SESSION_KEY")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)  # Tempo de expiração da sessão de 1 hora

# Configuração para upload de fotos
# Use diretório temporário em ambientes serverless (Vercel, Lambda)
UPLOAD_FOLDER = Path(os.getenv('UPLOAD_FOLDER', '/tmp/uploads'))
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
# Flask espera string path em config
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limite de 16MB

db = SQLAlchemy(app)

# Grupos fixos de produtos
PRODUCT_GROUPS = [
    "Implantes e componentes",
    "Dentística (resina)",
    "Material Básico",
    "Itens de Consumo",
    "Geral",
]


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class Mercadoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    codigo = db.Column(db.String(50), nullable=False, unique=True)
    grupo = db.Column(db.String(100), nullable=False, default="Geral")
    quantidade = db.Column(db.Integer, nullable=False)
    descricao = db.Column(db.String(200))
    preco = db.Column(db.Float)

    def __repr__(self):
        return f"<Mercadoria {self.nome}>"


class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100), nullable=True, unique=True)
    role = db.Column(db.String(50), nullable=False, default="funcionario")  # gerente, supervisor, funcionario

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# Context processor para sempre passar usuario para templates
@app.context_processor
def inject_usuario():
    usuario = None
    if "user_id" in session:
        try:
            usuario = Usuario.query.get(session["user_id"])
        except:
            usuario = None
    return {"usuario": usuario}


class Fornecedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cnpj = db.Column(db.String(18), nullable=False, unique=True)
    nome = db.Column(db.String(100), nullable=False)
    endereco = db.Column(db.String(200), nullable=False)
    telefone = db.Column(db.String(15), nullable=False)
    email = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<Fornecedor {self.nome}>'


class NotaFiscal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero_nf = db.Column(db.String(20), nullable=False, unique=True)
    data_emissao = db.Column(db.Date, nullable=False)
    data_entrega = db.Column(db.Date, nullable=False)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedor.id'), nullable=False)
    
    fornecedor = db.relationship('Fornecedor', backref=db.backref('notas_fiscais', lazy=True))

    def __repr__(self):
        return f'<NotaFiscal {self.numero_nf}>'


class ItemNotaFiscal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    preco_unitario = db.Column(db.Float, nullable=False)
    grupo = db.Column(db.String(50), nullable=True)  # Adicionando a coluna grupo
    nota_fiscal_id = db.Column(db.Integer, db.ForeignKey('nota_fiscal.id'), nullable=False)

    nota_fiscal = db.relationship('NotaFiscal', backref=db.backref('itens', lazy=True))

    def __repr__(self):
        return f'<ItemNotaFiscal {self.descricao}>'


class LogMovimentacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)
    acao = db.Column(db.String(100), nullable=False)
    mercadoria_id = db.Column(db.Integer, db.ForeignKey("mercadoria.id"), nullable=True)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedor.id"), nullable=True)
    descricao = db.Column(db.String(200), nullable=False)
    data_hora = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship("Usuario", backref=db.backref("logs", lazy=True))
    mercadoria = db.relationship("Mercadoria", backref=db.backref("logs", lazy=True))
    fornecedor = db.relationship("Fornecedor", backref=db.backref("logs", lazy=True))


class Cirurgia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_cirurgia = db.Column(db.Date, nullable=False)
    nome_paciente = db.Column(db.String(200), nullable=False)
    referencia_produto = db.Column(db.String(500), nullable=False)  # Referência do produto usado
    foto_path = db.Column(db.String(300), nullable=True)  # Caminho da foto armazenada
    mercadoria_id = db.Column(db.Integer, db.ForeignKey("mercadoria.id"), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=False)
    descricao = db.Column(db.String(500), nullable=True)  # Descrição adicional
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    
    usuario = db.relationship("Usuario", backref=db.backref("cirurgias", lazy=True))
    mercadoria = db.relationship("Mercadoria", backref=db.backref("cirurgias", lazy=True))
    
    def __repr__(self):
        return f"<Cirurgia {self.nome_paciente} - {self.data_cirurgia}>"


class Grupo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    descricao = db.Column(db.String(250), nullable=True)

    def __repr__(self):
        return f"<Grupo {self.nome}>"


# Função para criar um usuário inicial
def criar_usuario_inicial():
    """
    Cria um usuário gerente inicial se nenhum usuário existir no banco de dados.
    """
    if Usuario.query.first() is None:
        username = os.getenv("USER")
        password = os.getenv("PASSWORD")  # Altere esta senha para uma senha forte
        email = os.getenv("EMAIL", f"{username}@estoque.local")

        novo_usuario = Usuario(username=username, email=email, role="gerente")
        novo_usuario.set_password(password)
        db.session.add(novo_usuario)
        db.session.commit()

# Inicializando o banco de dados e criando um usuário inicial, se necessário
with app.app_context():
    db.create_all()
    
    # Garantir que as colunas `email` e `role` existem na tabela usuario (para bancos já existentes)
    try:
        inspector = db.inspect(db.engine)
        cols = [c["name"] for c in inspector.get_columns("usuario")]
        
        if "email" not in cols:
            db.session.execute(text("ALTER TABLE usuario ADD COLUMN email VARCHAR(100);"))
            db.session.commit()
        
        if "role" not in cols:
            db.session.execute(text("ALTER TABLE usuario ADD COLUMN role VARCHAR(50) DEFAULT 'funcionario';"))
            db.session.execute(text("UPDATE usuario SET role = 'gerente' WHERE id = (SELECT MIN(id) FROM usuario);"))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Warning: não foi possível garantir colunas de usuario automaticamente:", e)
    
    criar_usuario_inicial()

    # Garantir que a coluna `codigo` exista na tabela (para bancos já existentes).
    try:
        inspector = db.inspect(db.engine)
        cols = [c["name"] for c in inspector.get_columns("mercadoria")]
        if "codigo" not in cols:
            # adiciona coluna, popula com um valor único baseado no id, adiciona constraint e torna NOT NULL
            db.session.execute(text("ALTER TABLE mercadoria ADD COLUMN codigo VARCHAR(50);"))
            db.session.execute(text("UPDATE mercadoria SET codigo = 'm' || id::text WHERE codigo IS NULL OR codigo = '';"))
            db.session.execute(text("ALTER TABLE mercadoria ADD CONSTRAINT uq_mercadoria_codigo UNIQUE (codigo);"))
            db.session.execute(text("ALTER TABLE mercadoria ALTER COLUMN codigo SET NOT NULL;"))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Warning: não foi possível garantir coluna 'codigo' automaticamente:", e)

    # Garantir que a coluna `grupo` exista na tabela mercadoria (para bancos já existentes).
    try:
        inspector = db.inspect(db.engine)
        cols = [c["name"] for c in inspector.get_columns("mercadoria")]
        if "grupo" not in cols:
            db.session.execute(text("ALTER TABLE mercadoria ADD COLUMN grupo VARCHAR(100) DEFAULT 'Geral';"))
            db.session.execute(text("UPDATE mercadoria SET grupo = 'Geral' WHERE grupo IS NULL OR grupo = '';"))
            db.session.execute(text("ALTER TABLE mercadoria ALTER COLUMN grupo SET NOT NULL;"))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Warning: não foi possível garantir coluna 'grupo' automaticamente:", e)

    # Garantir que exista a tabela de grupos e popular com valores padrão se vazia
    try:
        if not Grupo.query.first():
            # Insere os grupos padrão se nenhum existir
            for nome in PRODUCT_GROUPS:
                g = Grupo(nome=nome)
                db.session.add(g)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Warning: não foi possível popular grupos padrão automaticamente:", e)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Por favor, faça login para acessar esta página.", "warning")
            return redirect(url_for("login"))
        session.modified = True  # Atualiza o tempo da sessão a cada requisição
        return f(*args, **kwargs)
    return decorated_function


def gerente_required(f):
    """Decorator para garantir que apenas gerentes acessem a rota."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Por favor, faça login para acessar esta página.", "warning")
            return redirect(url_for("login"))
        usuario = Usuario.query.get(session["user_id"])
        if not usuario or usuario.role != "gerente":
            flash("Você não tem permissão para acessar esta página. Apenas gerentes podem.", "error")
            return redirect(url_for("index"))
        session.modified = True
        return f(*args, **kwargs)
    return decorated_function


def registrar_log(acao, descricao, mercadoria_id=None, fornecedor_id=None):
    log = LogMovimentacao(
        usuario_id=session.get("user_id"),
        acao=acao,
        mercadoria_id=mercadoria_id,
        fornecedor_id=fornecedor_id,
        descricao=descricao,
    )
    db.session.add(log)
    db.session.commit()


@app.route("/")
@login_required
def index():
    mercadorias = Mercadoria.query.all()
    usuario = Usuario.query.get(session.get("user_id"))
    fornecedores = Fornecedor.query.order_by(Fornecedor.nome).all()
    # versão serializável para uso em JavaScript
    fornecedores_json = [ { 'id': f.id, 'nome': f.nome } for f in fornecedores ]
    return render_template("index.html", mercadorias=mercadorias, usuario=usuario, fornecedores=fornecedores, fornecedores_json=fornecedores_json)


@app.route("/adicionar", methods=["GET", "POST"])
@login_required
def adicionar():
    if request.method == "POST":
        form_type = request.form.get("form_type", "novo")
        # Novo cadastro de mercadoria
        if form_type == "novo":
            codigo = request.form["codigo"].strip()
            grupo = request.form.get("grupo", "Geral").strip()
            nome = request.form.get("nome", "").strip()
            try:
                quantidade = int(request.form["quantidade"])
            except Exception:
                quantidade = 0
            descricao = request.form.get("descricao")
            try:
                preco = float(request.form.get("preco", 0))
            except Exception:
                preco = 0.0
            mercadoria_existente = Mercadoria.query.filter(
                db.func.lower(Mercadoria.codigo) == codigo.lower()
            ).first()
            if mercadoria_existente:
                flash("Já existe uma mercadoria com esse código!", "error")
                return redirect(url_for("adicionar"))

            nova_mercadoria = Mercadoria(
                nome=nome or codigo,
                codigo=codigo,
                quantidade=quantidade,
                descricao=descricao,
                preco=preco,
                grupo=grupo,
            )
            db.session.add(nova_mercadoria)
            db.session.commit()
            registrar_log(
                "Inserção",
                f"Mercadoria '{nova_mercadoria.codigo}' adicionada com quantidade {quantidade}.",
                mercadoria_id=nova_mercadoria.id,
            )
            flash("Mercadoria adicionada com sucesso!", "success")
            return redirect(url_for("index"))

        # Movimentação (entrada/saída)
        if form_type == "movimentar":
            try:
                merc_id = int(request.form.get("mercadoria_id", 0))
            except Exception:
                merc_id = None
            mov_type = request.form.get("mov_type")
            try:
                mov_q = int(request.form.get("mov_quantidade", 0))
            except Exception:
                mov_q = 0
            mov_desc = request.form.get("mov_descricao", "")

            if not merc_id or mov_q <= 0 or mov_type not in ("entrada", "saida"):
                flash("Dados de movimentação inválidos.", "error")
                return redirect(url_for("adicionar"))

            merc = Mercadoria.query.get(merc_id)
            if not merc:
                flash("Mercadoria não encontrada.", "error")
                return redirect(url_for("adicionar"))

            if mov_type == "entrada":
                merc.quantidade = (merc.quantidade or 0) + mov_q
                acao = "Entrada"
                descricao_log = f"Entrada de {mov_q} na mercadoria '{merc.codigo}'. {mov_desc}"
            else:
                # saída
                if (merc.quantidade or 0) < mov_q:
                    flash("Quantidade insuficiente para saída.", "error")
                    return redirect(url_for("adicionar"))
                merc.quantidade = (merc.quantidade or 0) - mov_q
                acao = "Saída"
                descricao_log = f"Saída de {mov_q} da mercadoria '{merc.codigo}'. {mov_desc}"

            db.session.commit()
            registrar_log(acao, descricao_log, mercadoria_id=merc.id)
            flash(f"Movimentação '{acao}' registrada com sucesso.", "success")
            return redirect(url_for("index"))

    # fornecer lista de grupos, mercadorias e fornecedores para o formulário
    grupos = [g.nome for g in Grupo.query.order_by(Grupo.nome).all()]
    if not grupos:
        grupos = PRODUCT_GROUPS
    mercadorias = Mercadoria.query.order_by(Mercadoria.nome).all()
    fornecedores = Fornecedor.query.order_by(Fornecedor.nome).all()
    return render_template("adicionar.html", grupos=grupos, mercadorias=mercadorias, fornecedores=fornecedores)



@app.route('/nova_nf', methods=['POST'])
@login_required
def nova_nf():
    fornecedor_id = request.form.get('fornecedor_id')
    numero_nf = request.form.get('numero_nf')
    data_emissao = request.form.get('data_emissao')
    data_entrega = request.form.get('data_entrega')

    if not fornecedor_id or not numero_nf or not data_emissao or not data_entrega:
        flash('Todos os campos da Nota Fiscal são obrigatórios.', 'error')
        return redirect(url_for('adicionar'))

    fornecedor = Fornecedor.query.get(fornecedor_id)
    if not fornecedor:
        flash('Fornecedor não encontrado.', 'error')
        return redirect(url_for('adicionar'))

    # verificar duplicidade
    if NotaFiscal.query.filter_by(numero_nf=numero_nf).first():
        flash('Já existe uma Nota Fiscal com esse número!', 'error')
        return redirect(url_for('adicionar'))

    try:
        nova = NotaFiscal(
            numero_nf=numero_nf,
            data_emissao=datetime.strptime(data_emissao, '%Y-%m-%d').date(),
            data_entrega=datetime.strptime(data_entrega, '%Y-%m-%d').date(),
            fornecedor_id=fornecedor.id
        )
        db.session.add(nova)
        db.session.commit()
        registrar_log('Inserção NF', f"Nota Fiscal '{numero_nf}' criada para fornecedor '{fornecedor.nome}'.", fornecedor_id=fornecedor.id)
        flash('Nota Fiscal criada com sucesso!', 'success')
        return redirect(url_for('listar_notas_fiscais', fornecedor_id=fornecedor.id))
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao criar Nota Fiscal: {e}', 'error')
        return redirect(url_for('adicionar'))


@app.route("/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar(id):
    mercadoria = Mercadoria.query.get_or_404(id)
    if request.method == "POST":
        mercadoria.codigo = request.form["codigo"].strip()
        mercadoria.grupo = request.form.get("grupo", mercadoria.grupo).strip()
        mercadoria.nome = request.form.get("nome", mercadoria.nome).strip()
        mercadoria.quantidade = int(request.form["quantidade"])
        mercadoria.descricao = request.form["descricao"]
        mercadoria.preco = float(request.form["preco"])
        db.session.commit()
        registrar_log(
            "Edição",
            f"Mercadoria '{mercadoria.codigo}' editada. Quantidade: {mercadoria.quantidade}.",
            mercadoria_id=mercadoria.id,
        )
        flash("Mercadoria editada com sucesso!", "success")
        return redirect(url_for("index"))

    grupos = [g.nome for g in Grupo.query.order_by(Grupo.nome).all()]
    if not grupos:
        grupos = PRODUCT_GROUPS
    return render_template("editar.html", mercadoria=mercadoria, grupos=grupos)


@app.route("/excluir/<int:id>")
@login_required
def excluir(id):
    # Tenta buscar a mercadoria antes de excluí-la
    mercadoria = Mercadoria.query.get(id)
    
    if not mercadoria:
        flash("Mercadoria não encontrada.", "error")
        return redirect(url_for("index"))

    try:
        # Registrar o log antes de excluir a mercadoria
        registrar_log(
            acao="Exclusão",
            descricao=f"Mercadoria '{mercadoria.codigo}' excluída.",
            mercadoria_id=mercadoria.id
        )

        # Agora exclui a mercadoria
        db.session.delete(mercadoria)
        db.session.commit()
        flash("Mercadoria excluída com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir mercadoria: {str(e)}", "error")
    
    return redirect(url_for("index"))

@app.route("/buscar_ajax", methods=["GET"])
@login_required
def buscar_ajax():
    query = request.args.get("query", "").strip().lower()
    resultados = Mercadoria.query.filter(
        (Mercadoria.nome.ilike(f"%{query}%")) | (Mercadoria.codigo.ilike(f"%{query}%"))
    ).all()
    mercadorias = [
        {
            "id": mercadoria.id,
            "codigo": mercadoria.codigo,
            "grupo": mercadoria.grupo,
            "quantidade": mercadoria.quantidade,
            "descricao": mercadoria.descricao,
            "preco": mercadoria.preco,
        }
        for mercadoria in resultados
    ]
    return jsonify(mercadorias)

@app.route("/informacoes")
@login_required
def informacoes():
    logs = LogMovimentacao.query.order_by(LogMovimentacao.data_hora.desc()).all()
    return render_template("informacoes.html", logs=logs)


@app.route('/relatorios')
@login_required
def relatorios():
    # filtro por grupo opcional
    selected_grupo = request.args.get('grupo') or None
    query = Mercadoria.query
    if selected_grupo:
        query = query.filter_by(grupo=selected_grupo)
    mercadorias = query.order_by(Mercadoria.nome).all()
    grupos = [g.nome for g in Grupo.query.order_by(Grupo.nome).all()]
    return render_template('relatorios.html', mercadorias=mercadorias, grupos=grupos, selected_grupo=selected_grupo)


@app.route('/relatorios/export_excel')
@login_required
def relatorios_export_excel():
    if pd is None:
        flash('Dependência pandas não instalada no servidor.', 'error')
        return redirect(url_for('relatorios'))
    selected_grupo = request.args.get('grupo') or None
    query = Mercadoria.query
    if selected_grupo:
        query = query.filter_by(grupo=selected_grupo)
    mercadorias = query.order_by(Mercadoria.nome).all()
    data = [
        {
            'ID': m.id,
            'Código': m.codigo,
            'Nome': m.nome,
            'Grupo': m.grupo,
            'Quantidade': m.quantidade,
            'Descrição': m.descricao,
            'Preço': m.preco,
        }
        for m in mercadorias
    ]
    df = pd.DataFrame(data)
    output = io.BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    filename = f"relatorio_estoque_{selected_grupo or 'todos'}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/relatorios/export_pdf')
@login_required
def relatorios_export_pdf():
    selected_grupo = request.args.get('grupo') or None
    query = Mercadoria.query
    if selected_grupo:
        query = query.filter_by(grupo=selected_grupo)
    mercadorias = query.order_by(Mercadoria.nome).all()

    # Gerar PDF simples com ReportLab
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
        data = [["ID", "Código", "Nome", "Grupo", "Quantidade", "Descrição", "Preço"]]
        for m in mercadorias:
            data.append([m.id, m.codigo, m.nome, m.grupo, m.quantidade, m.descricao or '', f"R$ {m.preco}"])

        table = Table(data, repeatRows=1)
        style = TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN',(0,0),(-1,-1),'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ])
        table.setStyle(style)
        elements = [table]
        doc.build(elements)
        buffer.seek(0)
        filename = f"relatorio_estoque_{selected_grupo or 'todos'}.pdf"
        return send_file(buffer, download_name=filename, as_attachment=True, mimetype='application/pdf')
    except Exception as e:
        flash(f'Erro ao gerar PDF: {e}', 'error')
        return redirect(url_for('relatorios'))

@app.route("/fornecedores", methods=["GET", "POST"])
@login_required
def gerenciar_fornecedores():
    fornecedor_id = request.args.get('fornecedor_id')
    fornecedor = Fornecedor.query.get(fornecedor_id) if fornecedor_id else None

    if request.method == 'POST':
        cnpj = request.form['cnpj']
        nome = request.form['nome']
        endereco = request.form['endereco']
        telefone = request.form['telefone']
        email = request.form['email']

        if fornecedor:  # Editando fornecedor
            fornecedor_existente = Fornecedor.query.filter(
                Fornecedor.cnpj == cnpj, 
                Fornecedor.id != fornecedor.id
            ).first()
            if fornecedor_existente:
                flash('Já existe um fornecedor com esse CNPJ!', 'error')
                return redirect(url_for('gerenciar_fornecedores', fornecedor_id=fornecedor.id))

            fornecedor.cnpj = cnpj
            fornecedor.nome = nome
            fornecedor.endereco = endereco
            fornecedor.telefone = telefone
            fornecedor.email = email
            db.session.commit()
            registrar_log(
                "Edição Fornecedor",
                f"Fornecedor '{fornecedor.nome}' editado.",
                fornecedor_id=fornecedor.id,
            )
            flash('Fornecedor editado com sucesso!', 'success')
        else:  # Novo fornecedor
            fornecedor_existente = Fornecedor.query.filter_by(cnpj=cnpj).first()
            if fornecedor_existente:
                flash('Já existe um fornecedor com esse CNPJ!', 'error')
                return redirect(url_for('gerenciar_fornecedores'))

            novo_fornecedor = Fornecedor(
                cnpj=cnpj, 
                nome=nome, 
                endereco=endereco, 
                telefone=telefone, 
                email=email
            )
            db.session.add(novo_fornecedor)
            db.session.commit()
            registrar_log(
                "Inserção Fornecedor",
                f"Fornecedor '{novo_fornecedor.nome}' adicionado.",
                fornecedor_id=novo_fornecedor.id,
            )
            flash('Fornecedor adicionado com sucesso!', 'success')

        return redirect(url_for('gerenciar_fornecedores'))

    fornecedores = Fornecedor.query.all()
    return render_template('fornecedor.html', fornecedores=fornecedores, fornecedor=fornecedor)

@app.route('/excluir_fornecedor/<int:id>')
@login_required
def excluir_fornecedor(id):
    fornecedor = Fornecedor.query.get(id)
    
    if not fornecedor:
        flash("Fornecedor não encontrado.", "error")
        return redirect(url_for('gerenciar_fornecedores'))

    # Verificar se existem notas fiscais associadas
    notas_associadas = NotaFiscal.query.filter_by(fornecedor_id=fornecedor.id).all()
    if notas_associadas:
        flash("Não é possível excluir o fornecedor, pois existem notas fiscais associadas.", "error")
        return redirect(url_for('gerenciar_fornecedores'))

    try:
        registrar_log(
            acao="Exclusão Fornecedor",
            descricao=f"Fornecedor '{fornecedor.nome}' excluído.",
            fornecedor_id=fornecedor.id
        )

        # Agora exclui o fornecedor
        db.session.delete(fornecedor)
        db.session.commit()
        flash('Fornecedor excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir fornecedor: {str(e)}", "error")
    
    return redirect(url_for('gerenciar_fornecedores'))

@app.route("/fornecedores/<int:fornecedor_id>/nova_nf", methods=["GET", "POST"])
@login_required
def criar_nota_fiscal(fornecedor_id):
    fornecedor = Fornecedor.query.get_or_404(fornecedor_id)

    if request.method == "POST":
        numero_nf = request.form['numero_nf']
        data_emissao = request.form['data_emissao']
        data_entrega = request.form['data_entrega']

        # Validação básica para garantir que todos os campos foram preenchidos
        if not numero_nf or not data_emissao or not data_entrega:
            flash("Todos os campos são obrigatórios!", "error")
            return redirect(url_for('criar_nota_fiscal', fornecedor_id=fornecedor.id))

        try:
            # Verificar se já existe uma NF com o mesmo número
            nota_existente = NotaFiscal.query.filter_by(numero_nf=numero_nf).first()
            if nota_existente:
                flash('Já existe uma Nota Fiscal com esse número!', 'error')
                return redirect(url_for('criar_nota_fiscal', fornecedor_id=fornecedor.id))

            # Criar a nova Nota Fiscal
            nova_nf = NotaFiscal(
                numero_nf=numero_nf,
                data_emissao=datetime.strptime(data_emissao, "%Y-%m-%d").date(),
                data_entrega=datetime.strptime(data_entrega, "%Y-%m-%d").date(),
                fornecedor_id=fornecedor.id
            )

            db.session.add(nova_nf)
            db.session.commit()
            flash('Nota Fiscal criada com sucesso!', 'success')
            return redirect(url_for('listar_notas_fiscais', fornecedor_id=fornecedor.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao criar Nota Fiscal: {str(e)}", "error")
            return redirect(url_for('criar_nota_fiscal', fornecedor_id=fornecedor.id))

    return render_template("nova_nf.html", fornecedor=fornecedor)

@app.route("/fornecedores/<int:fornecedor_id>/nfs")
@login_required
def listar_notas_fiscais(fornecedor_id):
    fornecedor = Fornecedor.query.get_or_404(fornecedor_id)
    notas_fiscais = NotaFiscal.query.filter_by(fornecedor_id=fornecedor.id).all()
    return render_template("listar_nfs.html", fornecedor=fornecedor, notas_fiscais=notas_fiscais)

@app.route("/nota_fiscal/<int:nf_id>", methods=["GET", "POST"])
@login_required
def detalhar_nota_fiscal(nf_id):
    nota_fiscal = NotaFiscal.query.get_or_404(nf_id)

    if request.method == "POST":
        descricao = request.form['descricao']
        quantidade = int(request.form['quantidade'])
        preco_unitario = float(request.form['preco_unitario'])
        grupo = request.form['grupo']  # Novo campo do grupo

        novo_item = ItemNotaFiscal(
            descricao=descricao,
            quantidade=quantidade,
            preco_unitario=preco_unitario,
            grupo=grupo,  # Armazena o grupo selecionado
            nota_fiscal_id=nota_fiscal.id
        )
        try:
            db.session.add(novo_item)
            db.session.commit()
            flash('Item adicionado com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao adicionar item: {str(e)}", "error")

    return render_template("detalhar_nf.html", nota_fiscal=nota_fiscal)

@app.route("/nota_fiscal/<int:nf_id>/editar", methods=["GET", "POST"])
@login_required
def editar_nota_fiscal(nf_id):
    nota_fiscal = NotaFiscal.query.get_or_404(nf_id)

    if request.method == "POST":
        # Lógica de edição da Nota Fiscal
        nota_fiscal.numero_nf = request.form["numero_nf"]
        nota_fiscal.data_emissao = request.form["data_emissao"]
        nota_fiscal.data_entrega = request.form["data_entrega"]
        db.session.commit()
        flash("Nota Fiscal editada com sucesso!", "success")
        return redirect(url_for("listar_notas_fiscais", fornecedor_id=nota_fiscal.fornecedor_id))

    return render_template("editar_nf.html", nota_fiscal=nota_fiscal)

@app.route("/nota_fiscal/<int:nf_id>/excluir", methods=["POST"])
@login_required
def excluir_nota_fiscal(nf_id):
    nota_fiscal = NotaFiscal.query.get_or_404(nf_id)
    try:
        db.session.delete(nota_fiscal)
        db.session.commit()
        flash("Nota Fiscal excluída com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir Nota Fiscal: {str(e)}", "error")

    return redirect(url_for("listar_notas_fiscais", fornecedor_id=nota_fiscal.fornecedor_id))

@app.route("/nota_fiscal/<int:nf_id>/item/<int:item_id>/editar", methods=["GET", "POST"])
@login_required
def editar_item_nf(nf_id, item_id):
    nota_fiscal = NotaFiscal.query.get_or_404(nf_id)
    item = ItemNotaFiscal.query.get_or_404(item_id)

    if request.method == "POST":
        item.descricao = request.form['descricao']
        item.quantidade = int(request.form['quantidade'])
        item.preco_unitario = float(request.form['preco_unitario'])

        try:
            db.session.commit()
            flash('Item da Nota Fiscal editado com sucesso!', 'success')
            return redirect(url_for('detalhar_nota_fiscal', nf_id=nota_fiscal.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao editar item: {str(e)}", "error")
            return redirect(url_for('editar_item_nf', nf_id=nota_fiscal.id, item_id=item.id))

    return render_template("editar_item_nf.html", nota_fiscal=nota_fiscal, item=item)

@app.route("/nota_fiscal/<int:nf_id>/item/<int:item_id>/excluir", methods=["POST"])
@login_required
def excluir_item_nf(nf_id, item_id):
    item = ItemNotaFiscal.query.get_or_404(item_id)
    try:
        db.session.delete(item)
        db.session.commit()
        flash('Item da Nota Fiscal excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir item: {str(e)}", "error")
    return redirect(url_for('detalhar_nota_fiscal', nf_id=nf_id))


@app.route("/usuarios", methods=["GET"])
@gerente_required
def listar_usuarios():
    """Lista todos os usuários (apenas gerentes)."""
    usuarios = Usuario.query.all()
    return render_template("listar_usuarios.html", usuarios=usuarios)


@app.route("/usuarios/criar", methods=["GET", "POST"])
@gerente_required
def criar_usuario():
    """Criar novo usuário (apenas gerentes)."""
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip()
        password = request.form["password"].strip()
        role = request.form.get("role", "funcionario")
        
        # Validar campos obrigatórios
        if not username or not email or not password:
            flash("Username, email e senha são obrigatórios!", "error")
            return redirect(url_for("criar_usuario"))
        
        # Verificar duplicatas
        if Usuario.query.filter_by(username=username).first():
            flash("Username já existe!", "error")
            return redirect(url_for("criar_usuario"))
        
        if Usuario.query.filter_by(email=email).first():
            flash("Email já existe!", "error")
            return redirect(url_for("criar_usuario"))
        
        # Criar novo usuário
        novo_usuario = Usuario(username=username, email=email, role=role)
        novo_usuario.set_password(password)
        db.session.add(novo_usuario)
        db.session.commit()
        
        registrar_log("Criação de Usuário", f"Usuário '{username}' criado com role '{role}'.")
        flash(f"Usuário '{username}' criado com sucesso!", "success")
        return redirect(url_for("listar_usuarios"))
    
    return render_template("criar_usuario.html")


@app.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
@gerente_required
def editar_usuario(user_id):
    """Editar usuário (apenas gerentes)."""
    usuario = Usuario.query.get_or_404(user_id)
    
    if request.method == "POST":
        usuario.email = request.form["email"].strip()
        usuario.role = request.form.get("role", usuario.role)
        password = request.form.get("password", "").strip()
        
        # Atualizar senha se fornecida
        if password:
            usuario.set_password(password)
        
        db.session.commit()
        registrar_log("Edição de Usuário", f"Usuário '{usuario.username}' editado.")
        flash(f"Usuário '{usuario.username}' atualizado com sucesso!", "success")
        return redirect(url_for("listar_usuarios"))
    
    return render_template("editar_usuario.html", usuario=usuario)


@app.route("/usuarios/<int:user_id>/excluir", methods=["POST"])
@gerente_required
def excluir_usuario(user_id):
    """Excluir usuário (apenas gerentes, não pode excluir a si mesmo)."""
    usuario = Usuario.query.get_or_404(user_id)
    
    if usuario.id == session.get("user_id"):
        flash("Você não pode excluir sua própria conta!", "error")
        return redirect(url_for("listar_usuarios"))
    
    username = usuario.username
    try:
        db.session.delete(usuario)
        db.session.commit()
        registrar_log("Exclusão de Usuário", f"Usuário '{username}' excluído.")
        flash(f"Usuário '{username}' excluído com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir usuário: {str(e)}", "error")
    
    return redirect(url_for("listar_usuarios"))


@app.route('/grupos')
@gerente_required
def listar_grupos():
    grupos = Grupo.query.order_by(Grupo.nome).all()
    return render_template('listar_grupos.html', grupos=grupos)


@app.route('/grupos/criar', methods=['GET', 'POST'])
@gerente_required
def criar_grupo():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip()
        if not nome:
            flash('Nome do grupo é obrigatório!', 'error')
            return redirect(url_for('criar_grupo'))
        if Grupo.query.filter_by(nome=nome).first():
            flash('Já existe um grupo com esse nome!', 'error')
            return redirect(url_for('criar_grupo'))
        g = Grupo(nome=nome, descricao=descricao)
        db.session.add(g)
        db.session.commit()
        registrar_log('Criação de Grupo', f"Grupo '{nome}' criado.")
        flash('Grupo criado com sucesso!', 'success')
        return redirect(url_for('listar_grupos'))
    return render_template('criar_grupo.html')


@app.route('/grupos/<int:id>/editar', methods=['GET', 'POST'])
@gerente_required
def editar_grupo(id):
    grupo = Grupo.query.get_or_404(id)
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        descricao = request.form.get('descricao', '').strip()
        if not nome:
            flash('Nome do grupo é obrigatório!', 'error')
            return redirect(url_for('editar_grupo', id=id))
        existente = Grupo.query.filter(Grupo.nome == nome, Grupo.id != id).first()
        if existente:
            flash('Já existe outro grupo com esse nome!', 'error')
            return redirect(url_for('editar_grupo', id=id))
        old_name = grupo.nome
        grupo.nome = nome
        grupo.descricao = descricao
        # Atualiza mercadorias vinculadas para manter consistência
        try:
            Mercadoria.query.filter_by(grupo=old_name).update({"grupo": nome})
        except Exception:
            db.session.rollback()
            flash('Erro ao atualizar mercadorias vinculadas ao grupo.', 'error')
            return redirect(url_for('editar_grupo', id=id))
        db.session.commit()
        registrar_log('Edição de Grupo', f"Grupo '{nome}' editado.")
        flash('Grupo atualizado com sucesso!', 'success')
        return redirect(url_for('listar_grupos'))
    return render_template('editar_grupo.html', grupo=grupo)


@app.route('/grupos/<int:id>/excluir', methods=['POST'])
@gerente_required
def excluir_grupo(id):
    grupo = Grupo.query.get_or_404(id)
    # Antes de excluir, garantir que nenhuma mercadoria esteja ligada a esse grupo
    vinculadas = Mercadoria.query.filter_by(grupo=grupo.nome).first()
    if vinculadas:
        flash('Não é possível excluir o grupo: existem mercadorias vinculadas a ele.', 'error')
        return redirect(url_for('listar_grupos'))
    nome = grupo.nome
    try:
        db.session.delete(grupo)
        db.session.commit()
        registrar_log('Exclusão de Grupo', f"Grupo '{nome}' excluído.")
        flash('Grupo excluído com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir grupo: {e}', 'error')
    return redirect(url_for('listar_grupos'))


# ========== ROTAS DE CIRURGIA ==========

@app.route("/cirurgias")
@login_required
def listar_cirurgias():
    cirurgias = Cirurgia.query.order_by(Cirurgia.data_cirurgia.desc()).all()
    return render_template("listar_cirurgias.html", cirurgias=cirurgias)


@app.route("/cirurgias/criar", methods=["GET", "POST"])
@login_required
def criar_cirurgia():
    if request.method == "POST":
        try:
            data_cirurgia = request.form.get("data_cirurgia")
            nome_paciente = request.form.get("nome_paciente")
            referencia_produto = request.form.get("referencia_produto")
            mercadoria_id = request.form.get("mercadoria_id") or None
            descricao = request.form.get("descricao", "")
            
            foto_path = None
            if 'foto' in request.files:
                file = request.files['foto']
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
                    filename = timestamp + filename
                    file_path = Path(app.config['UPLOAD_FOLDER']) / filename
                    file.save(str(file_path))
                    foto_path = filename
            
            # Converte mercadoria_id para inteiro se não for None
            if mercadoria_id:
                try:
                    mercadoria_id = int(mercadoria_id)
                except:
                    mercadoria_id = None
            
            cirurgia = Cirurgia(
                data_cirurgia=data_cirurgia,
                nome_paciente=nome_paciente,
                referencia_produto=referencia_produto,
                mercadoria_id=mercadoria_id,
                usuario_id=session["user_id"],
                descricao=descricao,
                foto_path=foto_path
            )
            
            db.session.add(cirurgia)
            db.session.commit()
            registrar_log("Criação de Cirurgia", f"Nova cirurgia para paciente '{nome_paciente}' criada.")
            flash(f"Cirurgia registrada com sucesso!", "success")
            return redirect(url_for("listar_cirurgias"))
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao registrar cirurgia: {str(e)}", "error")
    
    mercadorias = Mercadoria.query.all()
    return render_template("criar_cirurgia.html", mercadorias=mercadorias)


@app.route("/cirurgias/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_cirurgia(id):
    cirurgia = Cirurgia.query.get_or_404(id)
    
    if request.method == "POST":
        try:
            cirurgia.data_cirurgia = request.form.get("data_cirurgia")
            cirurgia.nome_paciente = request.form.get("nome_paciente")
            cirurgia.referencia_produto = request.form.get("referencia_produto")
            mercadoria_id = request.form.get("mercadoria_id")
            if mercadoria_id:
                try:
                    cirurgia.mercadoria_id = int(mercadoria_id)
                except:
                    cirurgia.mercadoria_id = None
            else:
                cirurgia.mercadoria_id = None
            cirurgia.descricao = request.form.get("descricao", "")
            
            # Adiciona nova foto se fornecida
            if 'foto' in request.files:
                file = request.files['foto']
                if file and file.filename and allowed_file(file.filename):
                    # Remove foto antiga se existir
                    if cirurgia.foto_path:
                        old_path = Path(app.config['UPLOAD_FOLDER']) / cirurgia.foto_path
                        if old_path.exists():
                            old_path.unlink()

                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
                    filename = timestamp + filename
                    file_path = Path(app.config['UPLOAD_FOLDER']) / filename
                    file.save(str(file_path))
                    cirurgia.foto_path = filename
            
            db.session.commit()
            registrar_log("Edição de Cirurgia", f"Cirurgia de '{cirurgia.nome_paciente}' atualizada.")
            flash("Cirurgia atualizada com sucesso!", "success")
            return redirect(url_for("listar_cirurgias"))
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao atualizar cirurgia: {str(e)}", "error")
    
    mercadorias = Mercadoria.query.all()
    return render_template("editar_cirurgia.html", cirurgia=cirurgia, mercadorias=mercadorias)


@app.route("/cirurgias/<int:id>/excluir", methods=["POST"])
@login_required
def excluir_cirurgia(id):
    cirurgia = Cirurgia.query.get_or_404(id)
    nome_paciente = cirurgia.nome_paciente
    
    try:
        # Remove foto do servidor se existir
        if cirurgia.foto_path:
            foto_path = os.path.join(app.config['UPLOAD_FOLDER'], cirurgia.foto_path)
            if os.path.exists(foto_path):
                os.remove(foto_path)
        
        db.session.delete(cirurgia)
        db.session.commit()
        registrar_log("Exclusão de Cirurgia", f"Cirurgia de '{nome_paciente}' excluída.")
        flash(f"Cirurgia de '{nome_paciente}' excluída com sucesso!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao excluir cirurgia: {str(e)}", "error")
    
    return redirect(url_for("listar_cirurgias"))


@app.route("/cirurgias/<int:id>/foto")
@login_required
def download_foto_cirurgia(id):
    cirurgia = Cirurgia.query.get_or_404(id)
    if cirurgia.foto_path:
        return send_file(os.path.join(app.config['UPLOAD_FOLDER'], cirurgia.foto_path))
    return redirect(url_for("listar_cirurgias"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = Usuario.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            session.permanent = True  # Configura a sessão como permanente para respeitar a expiração configurada
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
        else:
            flash("Nome de usuário ou senha incorretos.", "error")

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    session.pop("user_id", None)
    flash("Logout realizado com sucesso!", "success")
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
