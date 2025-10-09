import express from 'express';
import session from 'express-session';
import SQLiteStoreFactory from 'connect-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';
import bcrypt from 'bcryptjs';
import { PrismaClient, RoleType, PaymentCategory, FundingType, PaymentStatus, ApprovalDecision } from './generated/prisma/index.js';
import nodemailer from 'nodemailer';
import { registerBankStubs } from './bank/bankStubs.js';
const SQLiteStore = SQLiteStoreFactory(session);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const app = express();
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.urlencoded({ extended: true }));
app.use(express.json());
const sessionStore = new SQLiteStore({ db: 'sessions.sqlite', dir: path.join(__dirname, '..', '.data') });
app.use(session({
    store: sessionStore,
    secret: process.env.SESSION_SECRET || 'change-me',
    resave: false,
    saveUninitialized: false,
    cookie: { maxAge: 1000 * 60 * 60 * 8 },
}));
// Register future bank integration stubs
registerBankStubs(app);
app.get('/', (_req, res) => {
    res.render('index', { user: res.locals.user || null });
});
// Prisma and auth helpers
const prisma = new PrismaClient();
app.use(async (req, res, next) => {
    if (!req.session.userId)
        return next();
    const user = await prisma.user.findUnique({ where: { id: req.session.userId }, include: { roles: true } });
    res.locals.user = user;
    res.locals.isTreasury = !!user?.roles.some((r) => r.role === RoleType.TREASURY);
    next();
});
function requireAuth(req, res, next) {
    if (!req.session.userId)
        return res.redirect('/login');
    next();
}
function requireRole(roles) {
    return async (req, res, next) => {
        if (!req.session.userId)
            return res.redirect('/login');
        const has = await prisma.userRole.findFirst({ where: { userId: req.session.userId, role: { in: roles } } });
        if (!has)
            return res.status(403).send('Forbidden');
        next();
    };
}
app.get('/login', (_req, res) => {
    res.render('login', { error: null });
});
app.post('/login', async (req, res) => {
    const { email, password } = req.body;
    const user = await prisma.user.findUnique({ where: { email } });
    if (!user)
        return res.render('login', { error: 'Invalid credentials' });
    const ok = await bcrypt.compare(password, user.passwordHash);
    if (!ok)
        return res.render('login', { error: 'Invalid credentials' });
    req.session.userId = user.id;
    res.redirect('/');
});
// Email setup (console fallback)
const transporter = process.env.SMTP_HOST
    ? nodemailer.createTransport({
        host: process.env.SMTP_HOST,
        port: Number(process.env.SMTP_PORT || 587),
        secure: false,
        auth: process.env.SMTP_USER
            ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS }
            : undefined,
    })
    : nodemailer.createTransport({ jsonTransport: true });
async function sendEmail(to, subject, text) {
    try {
        await transporter.sendMail({ from: process.env.MAIL_FROM || 'treasury@gusto.com', to, subject, text });
    }
    catch (err) {
        // eslint-disable-next-line no-console
        console.error('Email send failed', err);
    }
}
app.post('/logout', (req, res) => {
    req.session.destroy(() => res.redirect('/login'));
});
// Basic forms scaffolding
app.get('/requests/new/funding', requireAuth, async (_req, res) => {
    res.render('funding_new', { fundingTypes: Object.values(FundingType) });
});
app.get('/requests/new/ap', requireAuth, async (_req, res) => {
    res.render('ap_new');
});
app.get('/requests/new/specific', requireAuth, async (_req, res) => {
    res.render('specific_new');
});
// Simple queues and treasury dashboard
app.get('/me/requests', requireAuth, async (req, res) => {
    const list = await prisma.payment.findMany({ where: { createdById: req.session.userId }, orderBy: { submissionDate: 'desc' } });
    res.render('requests_list', { title: 'My Requests', list });
});
app.get('/approvals', requireAuth, async (req, res) => {
    // In a fuller implementation, filter to items this user is permitted to approve
    const list = await prisma.payment.findMany({ where: { status: { in: [PaymentStatus.PENDING_APPROVAL, PaymentStatus.PENDING_SECOND_APPROVAL] } }, orderBy: { submissionDate: 'desc' } });
    res.render('requests_list', { title: 'Approvals Queue', list });
});
app.get('/treasury', requireRole([RoleType.TREASURY]), async (_req, res) => {
    const list = await prisma.payment.findMany({ orderBy: { submissionDate: 'desc' } });
    res.render('requests_list', { title: 'Treasury Dashboard', list });
});
// Treasury-only: manage access and capabilities
app.get('/admin/access', requireRole([RoleType.TREASURY, RoleType.ADMIN]), async (_req, res) => {
    const users = await prisma.user.findMany({ include: { roles: true, capabilities: true }, orderBy: { email: 'asc' } });
    res.render('access_admin', { users, RoleType, PaymentCategory });
});
app.post('/admin/access/role', requireRole([RoleType.TREASURY, RoleType.ADMIN]), async (req, res) => {
    const { userId, role, enable } = req.body;
    if (enable === 'true') {
        await prisma.userRole.upsert({ where: { userId_role: { userId, role } }, update: {}, create: { userId, role } });
    }
    else {
        await prisma.userRole.deleteMany({ where: { userId, role } });
    }
    const user = await prisma.user.findUnique({ where: { id: userId } });
    if (user)
        await sendEmail(user.email, 'Access Updated', `Your role ${role} has been ${enable === 'true' ? 'granted' : 'revoked'}.`);
    res.redirect('/admin/access');
});
app.post('/admin/access/capability', requireRole([RoleType.TREASURY, RoleType.ADMIN]), async (req, res) => {
    const { userId, category, type } = req.body;
    await prisma.capability.upsert({ where: { userId_category: { userId, category } }, update: { type }, create: { userId, category, type } });
    const capUser = await prisma.user.findUnique({ where: { id: userId } });
    if (capUser)
        await sendEmail(capUser.email, 'Capability Updated', `Your capability for ${category} is now ${type}.`);
    res.redirect('/admin/access');
});
// Approve / reject endpoints
app.post('/requests/:id/approve', requireAuth, async (req, res) => {
    const userId = req.session.userId;
    const id = req.params.id;
    const payment = await prisma.payment.findUnique({ where: { id } });
    if (!payment)
        return res.status(404).send('Not found');
    // Prevent creator from approving their own request
    if (payment.createdById === userId)
        return res.status(403).send('Cannot approve your own request');
    // Ensure user has approve capability for the category
    const allowed = await prisma.capability.findFirst({ where: { userId, category: payment.category } });
    if (!allowed || (allowed.type !== 'APPROVE' && allowed.type !== 'BOTH'))
        return res.status(403).send('No approve permission');
    // Record approval if not already approved by this user
    await prisma.approval.upsert({
        where: { paymentId_reviewerId: { paymentId: payment.id, reviewerId: userId } },
        update: { decision: ApprovalDecision.APPROVE },
        create: { paymentId: payment.id, reviewerId: userId, decision: ApprovalDecision.APPROVE },
    });
    // Count approvals
    const approvals = await prisma.approval.count({ where: { paymentId: payment.id, decision: ApprovalDecision.APPROVE } });
    const nextStatus = approvals >= payment.requiredApprovals ? PaymentStatus.PENDING_TREASURY : PaymentStatus.PENDING_SECOND_APPROVAL;
    await prisma.payment.update({ where: { id: payment.id }, data: { status: nextStatus } });
    if (nextStatus === PaymentStatus.PENDING_TREASURY) {
        await sendEmail(['john.murphy@gusto.com', 'my.chau@gusto.com', 'ming.huey@gusto.com'], 'Payment ready for Treasury', `Payment ${payment.id} is ready for Treasury review.`);
    }
    res.redirect(`/requests/${payment.id}`);
});
app.post('/requests/:id/reject', requireAuth, async (req, res) => {
    const userId = req.session.userId;
    const id = req.params.id;
    const payment = await prisma.payment.findUnique({ where: { id } });
    if (!payment)
        return res.status(404).send('Not found');
    if (payment.createdById === userId)
        return res.status(403).send('Cannot reject your own request');
    const allowed = await prisma.capability.findFirst({ where: { userId, category: payment.category } });
    if (!allowed || (allowed.type !== 'APPROVE' && allowed.type !== 'BOTH'))
        return res.status(403).send('No approve permission');
    await prisma.approval.upsert({
        where: { paymentId_reviewerId: { paymentId: payment.id, reviewerId: userId } },
        update: { decision: ApprovalDecision.REJECT },
        create: { paymentId: payment.id, reviewerId: userId, decision: ApprovalDecision.REJECT },
    });
    await prisma.payment.update({ where: { id: payment.id }, data: { status: PaymentStatus.REJECTED } });
    res.redirect(`/requests/${payment.id}`);
});
// Treasury finalize
app.post('/requests/:id/treasury-approve', requireRole([RoleType.TREASURY]), async (req, res) => {
    const id = req.params.id;
    await prisma.payment.update({ where: { id }, data: { status: PaymentStatus.TREASURY_APPROVED } });
    const p = await prisma.payment.findUnique({ where: { id }, include: { createdBy: { select: { email: true } } } });
    if (p?.createdBy?.email)
        await sendEmail(p.createdBy.email, 'Payment Approved by Treasury', `Payment ${id} has been approved by Treasury.`);
    res.redirect(`/requests/${id}`);
});
app.post('/requests/:id/treasury-reject', requireRole([RoleType.TREASURY]), async (req, res) => {
    const id = req.params.id;
    await prisma.payment.update({ where: { id }, data: { status: PaymentStatus.TREASURY_REJECTED } });
    const p = await prisma.payment.findUnique({ where: { id }, include: { createdBy: { select: { email: true } } } });
    if (p?.createdBy?.email)
        await sendEmail(p.createdBy.email, 'Payment Rejected by Treasury', `Payment ${id} has been rejected by Treasury.`);
    res.redirect(`/requests/${id}`);
});
// Submission handlers with basic routing rules
app.post('/requests/new/funding', requireAuth, async (req, res) => {
    const userId = req.session.userId;
    const { fundingType, amount, reason } = req.body;
    const parsedAmount = Number(amount);
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0)
        return res.status(400).send('Invalid amount');
    // Ensure user has INITIATE/BOTH capability for FUNDING
    const canInit = await prisma.capability.findFirst({ where: { userId, category: PaymentCategory.FUNDING } });
    if (!canInit || (canInit.type !== 'INITIATE' && canInit.type !== 'BOTH'))
        return res.status(403).send('No initiate permission');
    // Determine required approvals based on amount and variance/duplicate checks
    // Simple heuristic: compare against median of past same-type funding amounts and +/-5%
    const previous = await prisma.payment.findMany({
        where: { category: PaymentCategory.FUNDING, fundingType },
        orderBy: { submissionDate: 'desc' },
        take: 20,
        select: { amount: true, submissionDate: true },
    });
    const amounts = previous.map((p) => Number(p.amount));
    const median = amounts.length ? amounts.sort((a, b) => a - b)[Math.floor(amounts.length / 2)] : parsedAmount;
    const denominator = median === 0 ? 1 : median;
    const varianceFlag = Math.abs(parsedAmount - (median ?? parsedAmount)) / denominator > 0.05;
    // Duplicate/repeat heuristic: if same amount and same type in the last 24h
    const duplicateFlag = previous.some((p) => Number(p.amount) === parsedAmount && Date.now() - new Date(p.submissionDate).getTime() < 24 * 3600 * 1000);
    const requiresTwoApprovals = parsedAmount >= 100000 || varianceFlag || duplicateFlag;
    const requiredApprovals = requiresTwoApprovals ? 2 : 1;
    const payment = await prisma.payment.create({
        data: {
            category: PaymentCategory.FUNDING,
            fundingType,
            amount: parsedAmount,
            reason,
            status: requiresTwoApprovals ? PaymentStatus.PENDING_SECOND_APPROVAL : PaymentStatus.PENDING_APPROVAL,
            requiredApprovals,
            varianceFlag,
            duplicateFlag,
            createdById: userId,
        },
    });
    // notify approvers for FUNDING category
    const approverEmailsFunding = (await prisma.capability.findMany({ where: { category: PaymentCategory.FUNDING }, include: { user: true } }))
        .filter((c) => c.type === 'APPROVE' || c.type === 'BOTH')
        .map((c) => c.user.email);
    await sendEmail(approverEmailsFunding, 'New Funding Request', `A new funding request ${payment.id} requires approval.`);
    res.redirect(`/requests/${payment.id}`);
});
app.post('/requests/new/ap', requireAuth, async (req, res) => {
    const userId = req.session.userId;
    const { amount, reason } = req.body;
    const parsedAmount = Number(amount);
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0)
        return res.status(400).send('Invalid amount');
    const canInit = await prisma.capability.findFirst({ where: { userId, category: PaymentCategory.AP_FUNDING } });
    if (!canInit || (canInit.type !== 'INITIATE' && canInit.type !== 'BOTH'))
        return res.status(403).send('No initiate permission');
    const requiresTwoApprovals = parsedAmount >= 100000;
    const payment = await prisma.payment.create({
        data: {
            category: PaymentCategory.AP_FUNDING,
            amount: parsedAmount,
            reason,
            status: requiresTwoApprovals ? PaymentStatus.PENDING_SECOND_APPROVAL : PaymentStatus.PENDING_APPROVAL,
            requiredApprovals: requiresTwoApprovals ? 2 : 1,
            createdById: userId,
        },
    });
    const approverEmailsAP = (await prisma.capability.findMany({ where: { category: PaymentCategory.AP_FUNDING }, include: { user: true } }))
        .filter((c) => c.type === 'APPROVE' || c.type === 'BOTH')
        .map((c) => c.user.email);
    await sendEmail(approverEmailsAP, 'New AP Funding Request', `A new AP funding request ${payment.id} requires approval.`);
    res.redirect(`/requests/${payment.id}`);
});
app.post('/requests/new/specific', requireAuth, async (req, res) => {
    const userId = req.session.userId;
    const { amount, reason } = req.body;
    const parsedAmount = Number(amount);
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0)
        return res.status(400).send('Invalid amount');
    const canInit = await prisma.capability.findFirst({ where: { userId, category: PaymentCategory.SPECIFIC } });
    if (!canInit || (canInit.type !== 'INITIATE' && canInit.type !== 'BOTH'))
        return res.status(403).send('No initiate permission');
    const requiresTwoApprovals = parsedAmount >= 100000;
    const payment = await prisma.payment.create({
        data: {
            category: PaymentCategory.SPECIFIC,
            amount: parsedAmount,
            reason,
            status: requiresTwoApprovals ? PaymentStatus.PENDING_SECOND_APPROVAL : PaymentStatus.PENDING_APPROVAL,
            requiredApprovals: requiresTwoApprovals ? 2 : 1,
            createdById: userId,
        },
    });
    const approverEmailsSpec = (await prisma.capability.findMany({ where: { category: PaymentCategory.SPECIFIC }, include: { user: true } }))
        .filter((c) => c.type === 'APPROVE' || c.type === 'BOTH')
        .map((c) => c.user.email);
    await sendEmail(approverEmailsSpec, 'New Specific Payment', `A new specific payment ${payment.id} requires approval.`);
    res.redirect(`/requests/${payment.id}`);
});
// Request detail
app.get('/requests/:id', requireAuth, async (req, res) => {
    const id = req.params.id;
    const payment = await prisma.payment.findUnique({ where: { id }, include: { approvals: { include: { reviewer: true } }, createdBy: true } });
    if (!payment)
        return res.status(404).send('Not found');
    res.render('request_show', { payment });
});
const port = Number(process.env.PORT || 3000);
app.listen(port, () => {
    // eslint-disable-next-line no-console
    console.log(`Server listening on http://localhost:${port}`);
});
//# sourceMappingURL=server.js.map