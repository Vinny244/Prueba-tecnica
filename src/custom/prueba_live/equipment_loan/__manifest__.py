{
    'name': 'Equipment Loan',
    'version': '18.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Gestión de préstamos de equipos de mantenimiento',
    'description': """
Módulo para registrar y controlar préstamos de equipos de mantenimiento al personal:
- Registro de préstamos con fecha de entrega y fecha prevista de devolución.
- Control del ciclo de vida: borrador -> prestado -> devuelto.
- Validación de fechas de entrega y devolución.
- Regla de unicidad de préstamo activo por equipo (con protección de concurrencia a nivel de BD).
- Identificación dinámica de préstamos vencidos.
- Botón inteligente con conteo optimizado en equipos de mantenimiento.
- Seguridad basada en roles (Gestor de préstamos vs Usuario interno).
- Acción planificada diaria para notificar al gestor sobre préstamos vencidos sin duplicidad.
    """,
    'author': 'Grupo Llanos C.A.',
    'depends': [
        'maintenance',
        'mail',
    ],
    'data': [
        'security/equipment_loan_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/equipment_loan_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
