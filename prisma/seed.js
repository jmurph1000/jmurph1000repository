import { PrismaClient, RoleType, PaymentCategory, CapabilityType } from '../src/generated/prisma/index.js';
import bcrypt from 'bcryptjs';
const prisma = new PrismaClient();
async function ensureRoles(userId, roles) {
    for (const role of roles) {
        await prisma.userRole.upsert({
            where: { userId_role: { userId, role } },
            update: {},
            create: { userId, role },
        });
    }
}
async function ensureCapabilities(userId, entries) {
    for (const { category, type } of entries) {
        await prisma.capability.upsert({
            where: { userId_category: { userId, category } },
            update: { type },
            create: { userId, category, type },
        });
    }
}
async function main() {
    const admins = [
        { email: 'john.murphy@gusto.com', name: 'John Murphy' },
        { email: 'my.chau@gusto.com', name: 'My Chau' },
        { email: 'ming.huey@gusto.com', name: 'Ming Huey' },
    ];
    const defaultPassword = process.env.SEED_DEFAULT_PASSWORD || 'ChangeMe123!';
    const passwordHash = await bcrypt.hash(defaultPassword, 10);
    for (const admin of admins) {
        const user = await prisma.user.upsert({
            where: { email: admin.email },
            update: { passwordHash },
            create: {
                email: admin.email,
                name: admin.name,
                passwordHash,
            },
        });
        await ensureRoles(user.id, [RoleType.ADMIN, RoleType.TREASURY]);
        await ensureCapabilities(user.id, [
            { category: PaymentCategory.FUNDING, type: CapabilityType.BOTH },
            { category: PaymentCategory.AP_FUNDING, type: CapabilityType.BOTH },
            { category: PaymentCategory.SPECIFIC, type: CapabilityType.BOTH },
        ]);
        // eslint-disable-next-line no-console
        console.log('Seeded admin user', user.email);
    }
    // Initiators / approvers per spec
    const initiators = [
        { email: 'glydel.arioste@gusto.com', name: 'Glydel Arioste' },
        { email: 'michelle.sparks@gusto.com', name: 'Michelle Sparks' },
        { email: 'diana.roig@gusto.com', name: 'Diana Roig' },
    ];
    for (const init of initiators) {
        const user = await prisma.user.upsert({
            where: { email: init.email },
            update: { passwordHash },
            create: {
                email: init.email,
                name: init.name,
                passwordHash,
            },
        });
        await ensureRoles(user.id, [RoleType.INITIATOR]);
        await ensureCapabilities(user.id, [
            { category: PaymentCategory.FUNDING, type: CapabilityType.INITIATE },
            { category: PaymentCategory.AP_FUNDING, type: CapabilityType.INITIATE },
            { category: PaymentCategory.SPECIFIC, type: CapabilityType.INITIATE },
        ]);
    }
    const approvers = [
        { email: 'ming.huey@gusto.com', name: 'Ming Huey' },
        { email: 'my.chau@gusto.com', name: 'My Chau' },
        { email: 'diana.roig@gusto.com', name: 'Diana Roig' },
        { email: 'michelle.sparks@gusto.com', name: 'Michelle Sparks' },
    ];
    for (const ap of approvers) {
        const user = await prisma.user.upsert({
            where: { email: ap.email },
            update: { passwordHash },
            create: {
                email: ap.email,
                name: ap.name,
                passwordHash,
            },
        });
        await ensureRoles(user.id, [RoleType.APPROVER]);
        await ensureCapabilities(user.id, [
            { category: PaymentCategory.FUNDING, type: CapabilityType.APPROVE },
            { category: PaymentCategory.AP_FUNDING, type: CapabilityType.APPROVE },
            { category: PaymentCategory.SPECIFIC, type: CapabilityType.APPROVE },
        ]);
    }
}
main()
    .then(async () => {
    await prisma.$disconnect();
})
    .catch(async (e) => {
    // eslint-disable-next-line no-console
    console.error(e);
    await prisma.$disconnect();
    process.exit(1);
});
//# sourceMappingURL=seed.js.map