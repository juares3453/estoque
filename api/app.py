from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
from dotenv import load_dotenv

import os

load_dotenv()

app = Flask(__name__)
# Configurando o SQLAlchemy para PostgreSQL
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SECRET_KEY"] = os.getenv("SESSION_KEY")  # Para utilizar mensagens flash
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)  # Tempo de expiração da sessão de 1 hora
db = SQLAlchemy(app)


class Mercadoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    quantidade = db.Column(db.Integer, nullable=False)
    descricao = db.Column(db.String(200))
    preco = db.Column(db.Float)

    def __repr__(self):
        return f"<Mercadoria {self.nome}>"


class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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


# Função para criar um usuário inicial
def criar_usuario_inicial():
    """
    Cria um usuário inicial se nenhum usuário existir no banco de dados.
    """
    if Usuario.query.first() is None:
        username = os.getenv("USER")
        password = os.getenv("PASSWORD")  # Altere esta senha para uma senha forte

        novo_usuario = Usuario(username=username)
        novo_usuario.set_password(password)
        db.session.add(novo_usuario)
        db.session.commit()

# Inicializando o banco de dados e criando um usuário inicial, se necessário
with app.app_context():
    db.create_all()
    criar_usuario_inicial()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Por favor, faça login para acessar esta página.", "warning")
            return redirect(url_for("login"))
        session.modified = True  # Atualiza o tempo da sessão a cada requisição
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
    return render_template("index.html", mercadorias=mercadorias)


@app.route("/adicionar", methods=["GET", "POST"])
@login_required
def adicionar():
    if request.method == "POST":
        nome = request.form["nome"].strip().lower()
        quantidade = int(request.form["quantidade"])
        descricao = request.form["descricao"]
        preco = float(request.form["preco"])

        mercadoria_existente = Mercadoria.query.filter(
            db.func.lower(Mercadoria.nome) == nome
        ).first()
        if mercadoria_existente:
            flash("Já existe uma mercadoria com esse nome!", "error")
            return redirect(url_for("adicionar"))

        nova_mercadoria = Mercadoria(
            nome=nome, quantidade=quantidade, descricao=descricao, preco=preco
        )
        db.session.add(nova_mercadoria)
        db.session.commit()
        registrar_log(
            "Inserção",
            f"Mercadoria '{nova_mercadoria.nome}' adicionada com quantidade {quantidade}.",
            mercadoria_id=nova_mercadoria.id,
        )
        flash("Mercadoria adicionada com sucesso!", "success")
        return redirect(url_for("index"))

    return render_template("adicionar.html")


@app.route("/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar(id):
    mercadoria = Mercadoria.query.get_or_404(id)
    if request.method == "POST":
        mercadoria.nome = request.form["nome"].strip().lower()
        mercadoria.quantidade = int(request.form["quantidade"])
        mercadoria.descricao = request.form["descricao"]
        mercadoria.preco = float(request.form["preco"])
        db.session.commit()
        registrar_log(
            "Edição",
            f"Mercadoria '{mercadoria.nome}' editada. Quantidade: {mercadoria.quantidade}.",
            mercadoria_id=mercadoria.id,
        )
        flash("Mercadoria editada com sucesso!", "success")
        return redirect(url_for("index"))

    return render_template("editar.html", mercadoria=mercadoria)


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
            descricao=f"Mercadoria '{mercadoria.nome}' excluída.",
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
    resultados = Mercadoria.query.filter(Mercadoria.nome.like(f"%{query}%")).all()
    mercadorias = [
        {
            "id": mercadoria.id,
            "nome": mercadoria.nome,
            "quantidade": mercadoria.quantidade,
            "descricao": mercadoria.descricao,
            "preco": mercadoria.preco,
        }
        for mercadoria in resultados
    ]
    return jsonify(mercadorias)

@app.route("/movimentacoes")
@login_required
def movimentacoes():
    logs = LogMovimentacao.query.order_by(LogMovimentacao.data_hora.desc()).all()
    return render_template("movimentacoes.html", logs=logs)

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
